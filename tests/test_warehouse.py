from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.quality import SpatialQualityPolicy
from geopulse.warehouse import (
    BatchLoadConfig,
    main,
    plan_spatial_load,
    publish_spatial_batch,
    read_connection_settings,
)

Row = tuple[datetime, str, str]


class FakeCursor:
    """Model the warehouse transaction boundary without a Snowflake account."""

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.result: list[tuple[object, ...]] = []
        self.description: list[tuple[str]] = []
        self.closed = False

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exception: object) -> None:
        self.closed = True

    def execute(self, sql: str, params: object = None) -> FakeCursor:
        normalized = " ".join(sql.upper().split())
        self.connection.statements.append((normalized, params))
        self.result = []
        if normalized.startswith("PUT "):
            self.description = [
                (name,)
                for name in (
                    "source",
                    "target",
                    "source_size",
                    "target_size",
                    "source_compression",
                    "target_compression",
                    "status",
                    "message",
                )
            ]
            self.result = [
                (
                    "part.parquet",
                    "part.parquet",
                    12,
                    12,
                    "NONE",
                    "NONE",
                    self.connection.upload_status,
                    "",
                )
            ]
        elif normalized.startswith("COPY INTO "):
            if self.connection.fail_copy:
                raise RuntimeError("COPY rejected an invalid Parquet field")
            self.description = [("file",), ("status",), ("rows_loaded",)]
            file_count = sum(sql.startswith("PUT ") for sql, _ in self.connection.statements)
            # Each call owns a new temporary stage, even when the same connection is reused.
            file_count -= self.connection.previous_upload_count
            self.connection.previous_upload_count += file_count
            count = len(self.connection.landing_rows)
            self.result = [
                (
                    f"file_{index}/part.parquet",
                    self.connection.copy_status,
                    count // file_count + self.connection.copy_count_delta,
                )
                for index in range(file_count)
            ]
        elif normalized.startswith("SELECT "):
            if "COUNT_IF" in normalized:
                rows = self.connection.landing_rows
                self.result = [
                    self.connection.landing_summary or (len(rows), len({row[1] for row in rows}), 0)
                ]
            elif "GROUP BY" in normalized:
                self.result = [(self.connection.duplicate_count,)]
            else:
                self.result = [
                    (
                        self.connection.published_count_override
                        if self.connection.published_count_override is not None
                        else sum(
                            self.connection.start <= row[0] < self.connection.end
                            for row in self.connection.rows
                        ),
                    )
                ]
        elif normalized == "BEGIN" or normalized.startswith("BEGIN TRANSACTION"):
            self.connection.snapshot = list(self.connection.rows)
        elif normalized.startswith("DELETE FROM "):
            start, end = (datetime.fromisoformat(value) for value in params)
            self.connection.rows = [
                row for row in self.connection.rows if not start <= row[0] < end
            ]
        elif normalized.startswith("INSERT INTO "):
            if self.connection.fail_insert:
                raise RuntimeError("INSERT failed after the batch DELETE")
            self.connection.rows.extend(self.connection.landing_rows)
        elif normalized == "COMMIT":
            self.connection.snapshot = None
            self.connection.commits += 1
        elif normalized == "ROLLBACK":
            if self.connection.snapshot is not None:
                self.connection.rows = self.connection.snapshot
                self.connection.snapshot = None
            self.connection.rollbacks += 1
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        return self.result[0] if self.result else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.result


class FakeConnection:
    def __init__(self, start: datetime, end: datetime) -> None:
        self.start = start
        self.end = end
        self.landing_rows: list[Row] = [
            (start, "dev_a", "store_a"),
            (start, "dev_a", "store_b"),
            (start + timedelta(hours=12), "dev_b", "store_a"),
            (end - timedelta(minutes=1), "dev_c", "store_b"),
        ]
        self.rows: list[Row] = [
            (start - timedelta(seconds=1), "prior_day", "store_a"),
            (start + timedelta(hours=1), "stale_same_day", "store_a"),
            (end, "next_day", "store_a"),
        ]
        self.statements: list[tuple[str, object]] = []
        self.snapshot: list[Row] | None = None
        self.landing_summary: tuple[int, int, int] | None = None
        self.duplicate_count = 0
        self.published_count_override: int | None = None
        self.fail_copy = False
        self.fail_insert = False
        self.upload_status = "UPLOADED"
        self.copy_status = "LOADED"
        self.copy_count_delta = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.previous_upload_count = 0
        self.last_cursor: FakeCursor | None = None

    def cursor(self) -> FakeCursor:
        self.last_cursor = FakeCursor(self)
        return self.last_cursor

    def close(self) -> None:
        self.closed = True


class WarehouseBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.matches = self.root / "matches"
        self.audit = self.root / "audit"
        self.audit.mkdir()
        metrics = {
            "raw_ping_rows": 4,
            "valid_ping_rows": 4,
            "rejected_ping_rows": 0,
            "raw_store_rows": 2,
            "valid_store_rows": 2,
            "rejected_store_rows": 0,
            "matched_ping_store_rows": 4,
            "matched_unique_devices": 3,
        }
        with (self.audit / "part-00000.json").open("w", encoding="utf-8") as handle:
            for metric, value in metrics.items():
                handle.write(json.dumps({"metric": metric, "value": value}) + "\n")
        # Spark can emit the same part basename in different UTC partitions.
        for partition in ("event_date=2026-09-28", "event_date=2026-09-29"):
            destination = self.matches / partition
            destination.mkdir(parents=True)
            (destination / "part-00000.parquet").write_bytes(b"PAR1\x00\x00\x00\x00PAR1")
        self.config = BatchLoadConfig(
            run_date=date(2026, 9, 29),
            matches_path=self.matches,
            audit_path=self.audit,
            policy=SpatialQualityPolicy(expected_ping_rows=4),
        )
        self.plan = plan_spatial_load(self.config)
        self.connection = FakeConnection(*self.config.utc_window)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _arguments(self) -> list[str]:
        return [
            "--run-date",
            "2026-09-29",
            "--matches",
            str(self.matches),
            "--audit",
            str(self.audit),
            "--expected-ping-rows",
            "4",
        ]

    def test_kolkata_calendar_day_spans_two_utc_dates(self) -> None:
        start, end = self.config.utc_window
        self.assertEqual(start, datetime(2026, 9, 28, 18, 30))
        self.assertEqual(end, datetime(2026, 9, 29, 18, 30))
        self.assertIsNone(start.tzinfo)
        self.assertIsNone(end.tzinfo)
        self.assertEqual(end - start, timedelta(days=1))

    def test_plan_includes_every_partition_and_serializes_without_credentials(self) -> None:
        self.assertEqual(len(self.plan.parquet_files), 2)
        self.assertEqual(len(set(self.plan.parquet_files)), 2)
        manifest = json.dumps(self.plan.as_dict())
        self.assertIn("2026-09-29", manifest)
        self.assertIn("2026-09-28T18:30:00", manifest)
        self.assertIn("2026-09-29T18:30:00", manifest)
        self.assertNotIn("password", manifest.lower())

    def test_retry_replaces_only_the_intended_local_day(self) -> None:
        first = publish_spatial_batch(self.connection, self.plan)
        after_first = list(self.connection.rows)
        second = publish_spatial_batch(self.connection, self.plan)
        self.assertEqual(first["status"], "published")
        self.assertEqual(first["loaded_rows"], 4)
        self.assertEqual(second["loaded_rows"], 4)
        self.assertEqual(self.connection.rows, after_first)
        self.assertEqual(len(self.connection.rows), 6)
        self.assertEqual(
            {row[1] for row in self.connection.rows},
            {"dev_a", "dev_b", "dev_c", "prior_day", "next_day"},
        )
        self.assertEqual(self.connection.commits, 2)
        self.assertEqual(self.connection.rollbacks, 0)
        deletes = [
            (sql, params)
            for sql, params in self.connection.statements
            if sql.startswith("DELETE FROM ")
        ]
        self.assertEqual(len(deletes), 2)
        for sql, params in deletes:
            self.assertIn("EVENT_TS >=", sql)
            self.assertIn("EVENT_TS <", sql)
            self.assertEqual(
                tuple(datetime.fromisoformat(value) for value in params), self.config.utc_window
            )
        self.assertFalse(self.connection.closed)

    def test_duplicate_part_basenames_have_distinct_stage_destinations(self) -> None:
        publish_spatial_batch(self.connection, self.plan)
        uploads = [sql for sql, _ in self.connection.statements if sql.startswith("PUT ")]
        self.assertEqual(len(uploads), 2)
        destinations = [sql.split(" @", 1)[1].split()[0] for sql in uploads]
        self.assertEqual(len(set(destinations)), 2)

    def test_landing_validation_failures_never_begin_target_transaction(self) -> None:
        cases = (((3, 3, 0), 0), ((4, 2, 0), 0), ((4, 3, 1), 0), ((4, 3, 0), 1))
        for summary, duplicates in cases:
            with self.subTest(summary=summary, duplicates=duplicates):
                connection = FakeConnection(*self.config.utc_window)
                connection.landing_summary = summary
                connection.duplicate_count = duplicates
                original = list(connection.rows)
                with self.assertRaises(ValueError):
                    publish_spatial_batch(connection, self.plan)
                self.assertEqual(connection.rows, original)
                self.assertFalse(any(sql.startswith("BEGIN") for sql, _ in connection.statements))
                self.assertFalse(
                    any(sql.startswith("DELETE FROM") for sql, _ in connection.statements)
                )
                self.assertEqual(connection.commits, 0)

    def test_copy_failure_keeps_target_untouched(self) -> None:
        self.connection.fail_copy = True
        original = list(self.connection.rows)
        with self.assertRaisesRegex(RuntimeError, "COPY rejected"):
            publish_spatial_batch(self.connection, self.plan)
        self.assertEqual(self.connection.rows, original)
        self.assertFalse(any(sql.startswith("BEGIN") for sql, _ in self.connection.statements))

    def test_unconfirmed_upload_prevents_copy_and_target_changes(self) -> None:
        self.connection.upload_status = "ERROR"
        original = list(self.connection.rows)
        with self.assertRaisesRegex(ValueError, "upload was not confirmed"):
            publish_spatial_batch(self.connection, self.plan)
        self.assertEqual(self.connection.rows, original)
        self.assertFalse(any(sql.startswith("COPY INTO") for sql, _ in self.connection.statements))
        self.assertFalse(any(sql.startswith("BEGIN") for sql, _ in self.connection.statements))

    def test_partial_copy_results_prevent_target_transaction(self) -> None:
        for status, delta in (("PARTIALLY_LOADED", 0), ("LOADED", -1)):
            with self.subTest(status=status, delta=delta):
                connection = FakeConnection(*self.config.utc_window)
                connection.copy_status = status
                connection.copy_count_delta = delta
                original = list(connection.rows)
                with self.assertRaisesRegex(ValueError, "COPY results"):
                    publish_spatial_batch(connection, self.plan)
                self.assertEqual(connection.rows, original)
                self.assertFalse(any(sql.startswith("BEGIN") for sql, _ in connection.statements))

    def test_replacement_transaction_contains_no_implicit_commit_ddl(self) -> None:
        publish_spatial_batch(self.connection, self.plan)
        statements = [sql for sql, _ in self.connection.statements]
        begin = statements.index("BEGIN TRANSACTION")
        commit = statements.index("COMMIT")
        self.assertEqual(commit - begin, 4)
        self.assertTrue(statements[begin + 1].startswith("DELETE FROM"))
        self.assertTrue(statements[begin + 2].startswith("INSERT INTO"))
        self.assertTrue(statements[begin + 3].startswith("SELECT COUNT(*)"))
        self.assertTrue(all(not sql.startswith("CREATE") for sql in statements[begin:commit]))

    def test_insert_failure_rolls_back_the_scoped_delete(self) -> None:
        self.connection.fail_insert = True
        original = list(self.connection.rows)
        with self.assertRaisesRegex(RuntimeError, "INSERT failed"):
            publish_spatial_batch(self.connection, self.plan)
        self.assertEqual(self.connection.rows, original)
        self.assertEqual(self.connection.rollbacks, 1)
        self.assertEqual(self.connection.commits, 0)

    def test_post_insert_count_mismatch_rolls_back(self) -> None:
        self.connection.published_count_override = 3
        original = list(self.connection.rows)
        with self.assertRaises(ValueError):
            publish_spatial_batch(self.connection, self.plan)
        self.assertEqual(self.connection.rows, original)
        self.assertEqual(self.connection.rollbacks, 1)
        self.assertEqual(self.connection.commits, 0)

    def test_dry_run_validates_files_without_reading_credentials_or_connecting(self) -> None:
        output = StringIO()
        with (
            patch("geopulse.warehouse.read_connection_settings") as settings,
            patch("geopulse.warehouse.connect_snowflake") as connect,
            redirect_stdout(output),
        ):
            self.assertEqual(main([*self._arguments(), "--dry-run"]), 0)
        settings.assert_not_called()
        connect.assert_not_called()
        self.assertIn("2026-09-29", json.dumps(json.loads(output.getvalue())))

    def test_invalid_audit_blocks_cli_before_connection(self) -> None:
        error = StringIO()
        arguments = self._arguments()
        arguments[-1] = "5"
        with patch("geopulse.warehouse.connect_snowflake") as connect, redirect_stderr(error):
            self.assertEqual(main(arguments), 1)
        connect.assert_not_called()
        self.assertIn("expected 5", error.getvalue())

    def test_connection_settings_require_one_authentication_method(self) -> None:
        environment = {
            "DBT_SNOWFLAKE_ACCOUNT": "account",
            "DBT_SNOWFLAKE_USER": "user",
            "DBT_SNOWFLAKE_WAREHOUSE": "warehouse",
            "DBT_SNOWFLAKE_PASSWORD": "example-password",
        }
        settings = read_connection_settings(environment)
        self.assertEqual(settings["account"], "account")
        self.assertEqual(settings["password"], "example-password")
        environment.pop("DBT_SNOWFLAKE_PASSWORD")
        with self.assertRaises(ValueError):
            read_connection_settings(environment)

        environment["GEOPULSE_SNOWFLAKE_PRIVATE_KEY_FILE"] = "protected-key.p8"
        key_settings = read_connection_settings(environment)
        self.assertEqual(key_settings["private_key_file"], "protected-key.p8")
        self.assertEqual(key_settings["authenticator"], "SNOWFLAKE_JWT")
        self.assertNotIn("password", key_settings)

    def test_invalid_target_identifier_is_rejected_before_sql(self) -> None:
        with self.assertRaises(ValueError):
            BatchLoadConfig(
                date(2026, 9, 29),
                self.matches,
                self.audit,
                SpatialQualityPolicy(expected_ping_rows=4),
                schema="SPATIAL; DROP TABLE T",
            )

    def test_cli_closes_session_and_hides_connector_error_details(self) -> None:
        for error_type in (RuntimeError, ValueError):
            with self.subTest(error_type=error_type):
                error = StringIO()
                with (
                    patch("geopulse.warehouse.read_connection_settings", return_value={}),
                    patch("geopulse.warehouse.connect_snowflake", return_value=self.connection),
                    patch(
                        "geopulse.warehouse.publish_spatial_batch",
                        side_effect=error_type("secret-token"),
                    ),
                    redirect_stderr(error),
                ):
                    self.assertEqual(main(self._arguments()), 1)
                self.assertTrue(self.connection.closed)
                self.assertIn(error_type.__name__, error.getvalue())
                self.assertNotIn("secret-token", error.getvalue())


if __name__ == "__main__":
    unittest.main()
