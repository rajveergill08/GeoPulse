from __future__ import annotations

import csv
import gzip
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.raw_warehouse import (  # noqa: E402
    RawBatchConfig,
    main,
    plan_raw_load,
    publish_raw_batch,
    read_connection_settings,
)
from geopulse.synthetic import CSV_FIELDS  # noqa: E402

Ping = tuple[datetime, str, bool, str]


class FakeCursor:
    """Simulate the SQL boundary, never accepting a permanent mutation early."""

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
            self.description = [("source",), ("status",)]
            self.result = [("mobile_pings.csv.gz", self.connection.upload_status)]
        elif normalized.startswith("COPY INTO "):
            if self.connection.fail_copy:
                raise RuntimeError("COPY exposed secret-token")
            self.description = [("file",), ("status",), ("rows_loaded",)]
            self.result = [
                (
                    "mobile_pings.csv.gz",
                    self.connection.copy_status,
                    len(self.connection.landing_rows) + self.connection.copy_count_delta,
                )
            ]
        elif normalized.startswith("SELECT "):
            if "COUNT_IF(NOT COALESCE" in normalized:
                self.result = [
                    self.connection.landing_summary
                    or (
                        len(self.connection.landing_rows),
                        len({ping[1] for ping in self.connection.landing_rows}),
                        0,
                    )
                ]
            elif "GROUP BY" in normalized:
                self.result = [(self.connection.duplicate_count,)]
            elif "COUNT_IF(LOCATION IS NULL)" in normalized:
                self.result = [
                    self.connection.target_summary
                    or (
                        sum(
                            self.connection.start <= ping[0] < self.connection.end
                            for ping in self.connection.rows
                        ),
                        sum(
                            self.connection.start <= ping[0] < self.connection.end and not ping[2]
                            for ping in self.connection.rows
                        ),
                    )
                ]
        elif normalized == "BEGIN TRANSACTION":
            self.connection.snapshot = list(self.connection.rows)
        elif normalized.startswith("DELETE FROM "):
            start, end = (datetime.fromisoformat(value) for value in params)
            self.connection.rows = [
                ping for ping in self.connection.rows if not start <= ping[0] < end
            ]
        elif normalized.startswith("INSERT INTO "):
            if self.connection.fail_insert:
                raise RuntimeError("INSERT exposed secret-token")
            filename = params[0]
            self.connection.rows.extend(
                (timestamp, device_id, geography, filename)
                for timestamp, device_id, geography, _ in self.connection.landing_rows
            )
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
        self.landing_rows: list[Ping] = [
            (start, "dev_a", True, ""),
            (start + timedelta(hours=1), "dev_a", True, ""),
            (end - timedelta(seconds=1), "dev_b", True, ""),
        ]
        self.rows: list[Ping] = [
            (start - timedelta(seconds=1), "previous", True, "old.csv"),
            (start + timedelta(hours=2), "stale", True, "old.csv"),
            (end, "next", True, "old.csv"),
        ]
        self.statements: list[tuple[str, object]] = []
        self.snapshot: list[Ping] | None = None
        self.landing_summary: tuple[int, int, int] | None = None
        self.target_summary: tuple[int, int] | None = None
        self.duplicate_count = 0
        self.upload_status = "UPLOADED"
        self.copy_status = "LOADED"
        self.copy_count_delta = 0
        self.fail_copy = False
        self.fail_insert = False
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


class RawWarehouseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "mobile_pings.csv.gz"
        self.rows = [
            ["dev_a", "2026-10-01T00:00:00+05:30", "12.90", "77.60", "5.0", "home"],
            ["dev_a", "2026-10-01T01:00:00+05:30", "12.91", "77.61", "6.0", "work"],
            ["dev_b", "2026-10-01T23:59:59+05:30", "12.92", "77.62", "7.0", "retail"],
        ]
        self._write_rows(self.rows)
        self.config = RawBatchConfig(date(2026, 10, 1), self.path, 3, 2)
        self.plan = plan_raw_load(self.config)
        self.connection = FakeConnection(*self.config.utc_window)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _write_rows(
        self,
        rows: list[list[str]],
        *,
        header: tuple[str, ...] = CSV_FIELDS,
        path: Path | None = None,
    ) -> None:
        destination = path or self.path
        opener = gzip.open if destination.name.endswith(".gz") else Path.open
        with opener(destination, mode="wt", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)

    def _arguments(self) -> list[str]:
        return [
            "--run-date",
            "2026-10-01",
            "--pings",
            str(self.path),
            "--expected-ping-rows",
            "3",
            "--expected-devices",
            "2",
        ]

    def test_retail_day_uses_aware_utc_bounds(self) -> None:
        start, end = self.config.utc_window
        self.assertEqual(start, datetime(2026, 9, 30, 18, 30, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 10, 1, 18, 30, tzinfo=UTC))
        self.assertEqual(end - start, timedelta(days=1))
        self.assertEqual(self.plan.ping_rows, 3)
        self.assertEqual(self.plan.unique_devices, 2)
        preview = json.dumps(self.plan.as_dict())
        self.assertIn("2026-09-30T18:30:00Z", preview)
        self.assertNotIn("dev_a", preview)
        self.assertNotIn("77.60", preview)

    def test_uncompressed_csv_is_supported(self) -> None:
        plain = self.root / "mobile_pings.csv"
        self._write_rows(self.rows, path=plain)
        config = RawBatchConfig(date(2026, 10, 1), plain, 3, 2)
        self.assertEqual(config.compression, "NONE")
        self.assertEqual(plan_raw_load(config).ping_rows, 3)
        connection = FakeConnection(*config.utc_window)
        publish_raw_batch(connection, plan_raw_load(config))
        copy = next(sql for sql, _ in connection.statements if sql.startswith("COPY INTO"))
        self.assertIn("COMPRESSION = NONE", copy)

    def test_bad_header_and_wrong_field_count_fail_before_upload(self) -> None:
        self._write_rows(self.rows, header=tuple(reversed(CSV_FIELDS)))
        with self.assertRaisesRegex(ValueError, "header"):
            plan_raw_load(self.config)
        self._write_rows([self.rows[0][:-1]])
        with self.assertRaisesRegex(ValueError, "six fields"):
            plan_raw_load(self.config)
        self._write_rows([self.rows[0] + ["extra"]])
        with self.assertRaisesRegex(ValueError, "six fields"):
            plan_raw_load(self.config)

    def test_invalid_source_fields_are_rejected_without_values_in_errors(self) -> None:
        failures = (
            (0, "device-secret", ""),
            (5, "activity-secret", " "),
            (1, "time-secret", "2026-10-01T00:00:00"),
            (1, "time-secret", "2026-10-01T00:00:00+00:00"),
            (1, "time-secret", "2026-10-02T00:00:00+05:30"),
            (1, "time-secret", "not-a-date"),
            (2, "coordinate-secret", "NaN"),
            (2, "coordinate-secret", "91"),
            (3, "coordinate-secret", "181"),
            (4, "accuracy-secret", "0"),
            (4, "accuracy-secret", "Infinity"),
        )
        for index, secret, replacement in failures:
            with self.subTest(index=index, replacement=replacement):
                row = list(self.rows[0])
                row[index] = replacement
                self._write_rows([row])
                with self.assertRaises(ValueError) as error:
                    plan_raw_load(self.config)
                self.assertNotIn(secret, str(error.exception))
                self.assertIn("row 2", str(error.exception))

    def test_gzip_crc_and_count_mismatches_are_caught(self) -> None:
        compressed = self.path.read_bytes()
        self.path.write_bytes(compressed[:-5])
        with self.assertRaisesRegex(ValueError, "could not be read completely"):
            plan_raw_load(self.config)
        self._write_rows(self.rows)
        with self.assertRaisesRegex(ValueError, "expected 4"):
            plan_raw_load(RawBatchConfig(date(2026, 10, 1), self.path, 4, 2))
        with self.assertRaisesRegex(ValueError, "expected 3"):
            plan_raw_load(RawBatchConfig(date(2026, 10, 1), self.path, 3, 3))

    def test_retry_replaces_one_day_and_preserves_adjacent_days(self) -> None:
        first = publish_raw_batch(self.connection, self.plan)
        after_first = list(self.connection.rows)
        second = publish_raw_batch(self.connection, self.plan)
        self.assertEqual(first["status"], "published")
        self.assertEqual(second["loaded_rows"], 3)
        self.assertEqual(self.connection.rows, after_first)
        self.assertEqual(len(self.connection.rows), 5)
        self.assertEqual(self.connection.commits, 2)
        self.assertEqual(self.connection.rollbacks, 0)
        deletes = [
            (sql, params)
            for sql, params in self.connection.statements
            if sql.startswith("DELETE FROM ")
        ]
        self.assertEqual(len(deletes), 2)
        for sql, params in deletes:
            self.assertIn("EVENT_TS >= %S::TIMESTAMP_TZ", sql)
            self.assertEqual(
                tuple(datetime.fromisoformat(value) for value in params),
                self.config.utc_window,
            )
        inserts = [
            params for sql, params in self.connection.statements if sql.startswith("INSERT INTO ")
        ]
        self.assertEqual(inserts, [(self.path.name,), (self.path.name,)])

    def test_upload_and_direct_csv_copy_are_strict(self) -> None:
        publish_raw_batch(self.connection, self.plan)
        statements = [sql for sql, _ in self.connection.statements]
        put = next(sql for sql in statements if sql.startswith("PUT "))
        copy = next(sql for sql in statements if sql.startswith("COPY INTO "))
        self.assertIn("AUTO_COMPRESS = FALSE", put)
        self.assertIn("COMPRESSION = GZIP", copy)
        self.assertIn("SKIP_HEADER = 1", copy)
        self.assertIn("ERROR_ON_COLUMN_COUNT_MISMATCH = TRUE", copy)
        self.assertIn("ON_ERROR = ABORT_STATEMENT", copy)
        self.assertNotIn("FROM (SELECT", copy)
        self.assertIn("TO_CHAR(TRY_TO_TIMESTAMP_TZ(EVENT_TS_RAW), 'TZH:TZM')", " ".join(statements))
        self.assertIn(
            "TRY_TO_DOUBLE(ACCURACY_M_RAW) <= 1.7976931348623157E308", " ".join(statements)
        )
        self.assertIn(
            "ST_MAKEPOINT(TRY_TO_DOUBLE(LONGITUDE_RAW), TRY_TO_DOUBLE(LATITUDE_RAW))",
            " ".join(statements),
        )

    def test_unconfirmed_upload_blocks_copy_and_permanent_changes(self) -> None:
        self.connection.upload_status = "SKIPPED"
        original = list(self.connection.rows)
        with self.assertRaisesRegex(ValueError, "upload was not confirmed"):
            publish_raw_batch(self.connection, self.plan)
        self.assertEqual(self.connection.rows, original)
        self.assertFalse(any(sql.startswith("COPY INTO ") for sql, _ in self.connection.statements))
        self.assertFalse(any(sql == "BEGIN TRANSACTION" for sql, _ in self.connection.statements))

    def test_copy_failure_or_partial_copy_never_starts_transaction(self) -> None:
        for fail, status, delta in (
            (True, "LOADED", 0),
            (False, "PARTIALLY_LOADED", 0),
            (False, "LOADED", -1),
        ):
            with self.subTest(fail=fail, status=status, delta=delta):
                connection = FakeConnection(*self.config.utc_window)
                connection.fail_copy = fail
                connection.copy_status = status
                connection.copy_count_delta = delta
                original = list(connection.rows)
                with self.assertRaises((RuntimeError, ValueError)):
                    publish_raw_batch(connection, self.plan)
                self.assertEqual(connection.rows, original)
                self.assertFalse(
                    any(sql == "BEGIN TRANSACTION" for sql, _ in connection.statements)
                )

    def test_landing_count_type_offset_and_duplicate_fail_before_begin(self) -> None:
        for summary, duplicates in (
            ((2, 2, 0), 0),
            ((3, 1, 0), 0),
            ((3, 2, 1), 0),
            ((3, 2, 0), 1),
        ):
            with self.subTest(summary=summary, duplicates=duplicates):
                connection = FakeConnection(*self.config.utc_window)
                connection.landing_summary = summary
                connection.duplicate_count = duplicates
                original = list(connection.rows)
                with self.assertRaises(ValueError):
                    publish_raw_batch(connection, self.plan)
                self.assertEqual(connection.rows, original)
                self.assertFalse(
                    any(sql == "BEGIN TRANSACTION" for sql, _ in connection.statements)
                )

    def test_transaction_is_dml_only_and_bad_insert_rolls_back(self) -> None:
        self.connection.fail_insert = True
        original = list(self.connection.rows)
        with self.assertRaisesRegex(RuntimeError, "INSERT"):
            publish_raw_batch(self.connection, self.plan)
        self.assertEqual(self.connection.rows, original)
        self.assertEqual(self.connection.rollbacks, 1)
        self.assertEqual(self.connection.commits, 0)
        statements = [sql for sql, _ in self.connection.statements]
        begin = statements.index("BEGIN TRANSACTION")
        rollback = statements.index("ROLLBACK")
        self.assertTrue(statements[begin + 1].startswith("DELETE FROM "))
        self.assertTrue(statements[begin + 2].startswith("INSERT INTO "))
        self.assertFalse(any(sql.startswith("CREATE") for sql in statements[begin:rollback]))

    def test_wrong_post_insert_count_or_null_geography_rolls_back(self) -> None:
        for summary in ((2, 0), (3, 1)):
            with self.subTest(summary=summary):
                connection = FakeConnection(*self.config.utc_window)
                connection.target_summary = summary
                original = list(connection.rows)
                with self.assertRaisesRegex(ValueError, "Target ping count or geography"):
                    publish_raw_batch(connection, self.plan)
                self.assertEqual(connection.rows, original)
                self.assertEqual(connection.rollbacks, 1)
                self.assertEqual(connection.commits, 0)

    def test_dry_run_does_not_read_credentials_or_connect(self) -> None:
        output = StringIO()
        with (
            patch("geopulse.raw_warehouse.read_connection_settings") as settings,
            patch("geopulse.raw_warehouse.connect_snowflake") as connect,
            redirect_stdout(output),
        ):
            self.assertEqual(main([*self._arguments(), "--dry-run"]), 0)
        settings.assert_not_called()
        connect.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "validated")

    def test_bad_input_blocks_connect_before_credentials(self) -> None:
        self._write_rows(self.rows[:-1])
        error = StringIO()
        with (
            patch("geopulse.raw_warehouse.read_connection_settings") as settings,
            patch("geopulse.raw_warehouse.connect_snowflake") as connect,
            redirect_stderr(error),
        ):
            self.assertEqual(main(self._arguments()), 1)
        settings.assert_not_called()
        connect.assert_not_called()
        self.assertIn("expected 3", error.getvalue())

    def test_raw_settings_override_spatial_schema_and_support_key_auth(self) -> None:
        environment = {
            "DBT_SNOWFLAKE_ACCOUNT": "account",
            "DBT_SNOWFLAKE_USER": "user",
            "DBT_SNOWFLAKE_WAREHOUSE": "warehouse",
            "DBT_SNOWFLAKE_PASSWORD": "password-secret",
            "DBT_SNOWFLAKE_SOURCE_SCHEMA": "SPATIAL",
        }
        settings = read_connection_settings(environment)
        self.assertEqual(settings["schema"], "RAW")
        self.assertEqual(settings["session_parameters"]["QUERY_TAG"], "geopulse_raw_publisher")
        self.assertEqual(settings["password"], "password-secret")
        environment.pop("DBT_SNOWFLAKE_PASSWORD")
        with self.assertRaises(ValueError):
            read_connection_settings(environment)
        environment["GEOPULSE_SNOWFLAKE_PRIVATE_KEY_FILE"] = "key.p8"
        self.assertEqual(read_connection_settings(environment)["authenticator"], "SNOWFLAKE_JWT")

    def test_unquoted_target_identifiers_are_validated(self) -> None:
        for kwargs in (
            {"database": "GEO; DROP TABLE X"},
            {"schema": "RAW; DROP TABLE X"},
            {"schema": "SPATIAL"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RawBatchConfig(date(2026, 10, 1), self.path, 3, 2, **kwargs)

    def test_cli_closes_session_and_suppresses_connector_error_details(self) -> None:
        for error_type in (RuntimeError, ValueError):
            with self.subTest(error_type=error_type):
                connection = FakeConnection(*self.config.utc_window)
                error = StringIO()
                with (
                    patch("geopulse.raw_warehouse.read_connection_settings", return_value={}),
                    patch("geopulse.raw_warehouse.connect_snowflake", return_value=connection),
                    patch(
                        "geopulse.raw_warehouse.publish_raw_batch",
                        side_effect=error_type("secret-token"),
                    ),
                    redirect_stderr(error),
                ):
                    self.assertEqual(main(self._arguments()), 1)
                self.assertTrue(connection.closed)
                self.assertIn(error_type.__name__, error.getvalue())
                self.assertNotIn("secret-token", error.getvalue())


if __name__ == "__main__":
    unittest.main()
