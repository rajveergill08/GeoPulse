from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.dashboard_export import (
    HOURLY_COLUMNS,
    MART_COLUMNS,
    DashboardExportConfig,
    DashboardExportError,
    build_snapshot,
    fetch_aggregate_rows,
    fetch_hourly_rows,
    main,
    read_dashboard_connection_settings,
    read_stores,
    write_snapshot_atomically,
)

STORES_CSV = (
    "store_id,store_name,status,latitude,longitude,catchment_radius_m\n"
    "store_a,Store A,existing,12.9756,77.6066,500\n"
    "store_b,Store B,proposed,12.9719,77.6070,500\n"
    "store_c,Store C,candidate,12.9784,77.6408,750\n"
)


def mart_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "existing_store_id": "store_a",
        "candidate_store_id": "store_b",
        "candidate_store_status": "proposed",
        "traffic_date_local": date(2026, 9, 30),
        "retail_timezone": "Asia/Kolkata",
        "daypart": "morning_commute",
        "existing_store_unique_visitors": Decimal("10"),
        "candidate_store_unique_visitors": Decimal("4"),
        "shared_visitors": Decimal("3"),
        "incremental_candidate_visitors": Decimal("1"),
        "cannibalization_rate": Decimal("0.300000"),
        "candidate_overlap_rate": Decimal("0.750000"),
        "candidate_incremental_reach_rate": Decimal("0.250000"),
    }
    row.update(changes)
    return row


def hourly_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "store_id": "store_a",
        "traffic_date_local": date(2026, 9, 30),
        "event_hour_local": 8,
        "retail_timezone": "Asia/Kolkata",
        "unique_visitors": Decimal("10"),
        "ping_count": Decimal("12"),
    }
    row.update(changes)
    return row


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.description = [(name.upper(),) for name in MART_COLUMNS]
        self.columns = MART_COLUMNS

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        self.connection.cursor_closed = True

    def execute(self, sql: str, parameters: object = None) -> FakeCursor:
        self.connection.statements.append((sql, parameters))
        if "FCT_STORE_HOURLY_FOOTFALL" in sql:
            self.columns = HOURLY_COLUMNS
            self.description = [(name.upper(),) for name in HOURLY_COLUMNS]
        if self.connection.fail_query:
            raise RuntimeError("secret-password: query failed")
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        if self.columns == HOURLY_COLUMNS:
            rows = self.connection.hourly_rows
        else:
            rows = self.connection.rows
        return [tuple(row[name] for name in self.columns) for row in rows]


class FakeConnection:
    def __init__(
        self,
        rows: list[dict[str, object]] | None = None,
        hourly_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else [mart_row()]
        self.hourly_rows = (
            hourly_rows
            if hourly_rows is not None
            else [hourly_row(), hourly_row(store_id="store_b", unique_visitors=4, ping_count=5)]
        )
        self.statements: list[tuple[str, object]] = []
        self.fail_query = False
        self.closed = False
        self.cursor_closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


class DashboardExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.stores_path = self.root / "stores.csv"
        self.stores_path.write_text(STORES_CSV, encoding="utf-8")
        self.output_path = self.root / "output" / "dashboard.json"
        self.config = DashboardExportConfig(date(2026, 9, 30), self.stores_path, self.output_path)
        self.stores = read_stores(self.stores_path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _args(self, *, synthetic: bool = True) -> list[str]:
        args = [
            "--run-date",
            "2026-09-30",
            "--stores",
            str(self.stores_path),
            "--output",
            str(self.output_path),
        ]
        if synthetic:
            args.append("--synthetic")
        return args

    def test_dbt_mart_is_derived_from_target_schema_not_base_schema(self) -> None:
        self.assertEqual(
            self.config.mart_table, "GEOPULSE.ANALYTICS_MARTS.FCT_STORE_CANNIBALIZATION"
        )
        self.assertEqual(
            self.config.hourly_mart_table,
            "GEOPULSE.ANALYTICS_MARTS.FCT_STORE_HOURLY_FOOTFALL",
        )
        configured = DashboardExportConfig(
            date(2026, 9, 30),
            self.stores_path,
            self.output_path,
            database="retail_db",
            dbt_schema="analytics_dev",
        )
        self.assertEqual(
            configured.mart_table, "RETAIL_DB.ANALYTICS_DEV_MARTS.FCT_STORE_CANNIBALIZATION"
        )
        self.assertEqual(
            configured.hourly_mart_table,
            "RETAIL_DB.ANALYTICS_DEV_MARTS.FCT_STORE_HOURLY_FOOTFALL",
        )

    def test_db_identifiers_and_output_collision_are_rejected(self) -> None:
        for values in (
            {"database": "GEOPULSE;DROP TABLE X"},
            {"dbt_schema": "ANALYTICS.X"},
        ):
            with self.subTest(values=values), self.assertRaises(DashboardExportError):
                DashboardExportConfig(
                    date(2026, 9, 30), self.stores_path, self.output_path, **values
                )
        with self.assertRaises(DashboardExportError):
            DashboardExportConfig(date(2026, 9, 30), self.stores_path, self.stores_path)

    def test_invalid_timezone_is_rejected(self) -> None:
        with self.assertRaises(DashboardExportError):
            DashboardExportConfig(
                date(2026, 9, 30),
                self.stores_path,
                self.output_path,
                retail_timezone="not/a/timezone",
            )

    def test_query_is_read_only_aggregate_only_and_date_is_bound(self) -> None:
        connection = FakeConnection()
        rows = fetch_aggregate_rows(connection, self.config)
        self.assertEqual(rows, [mart_row()])
        self.assertTrue(connection.cursor_closed)
        self.assertEqual(len(connection.statements), 1)
        sql, parameters = connection.statements[0]
        self.assertTrue(sql.startswith("SELECT "))
        self.assertIn(self.config.mart_table, sql)
        self.assertIn("TO_DATE(%s)", sql)
        self.assertNotIn("2026-09-30", sql)
        self.assertNotIn("DEVICE_ID", sql)
        self.assertEqual(parameters, ("2026-09-30",))

    def test_hourly_query_is_read_only_aggregate_only_and_date_is_bound(self) -> None:
        connection = FakeConnection()
        rows = fetch_hourly_rows(connection, self.config)
        self.assertEqual(rows, connection.hourly_rows)
        self.assertTrue(connection.cursor_closed)
        self.assertEqual(len(connection.statements), 1)
        sql, parameters = connection.statements[0]
        self.assertTrue(sql.startswith("SELECT "))
        self.assertIn(", ".join(HOURLY_COLUMNS), sql)
        self.assertIn(self.config.hourly_mart_table, sql)
        self.assertIn("TO_DATE(%s)", sql)
        self.assertNotIn("2026-09-30", sql)
        self.assertNotIn("DEVICE_ID", sql)
        self.assertNotIn("LATITUDE", sql)
        self.assertEqual(parameters, ("2026-09-30",))

    def test_mart_column_mismatch_is_rejected(self) -> None:
        connection = FakeConnection()
        bad_cursor = connection.cursor()
        bad_cursor.description = [("DEVICE_ID",)]
        with patch.object(connection, "cursor", return_value=bad_cursor):
            with self.assertRaisesRegex(DashboardExportError, "unexpected aggregate columns"):
                fetch_aggregate_rows(connection, self.config)

    def test_hourly_mart_column_mismatch_is_rejected(self) -> None:
        connection = FakeConnection()
        bad_cursor = connection.cursor()
        bad_cursor.description = [("DEVICE_ID",)]
        with (
            patch.object(connection, "cursor", return_value=bad_cursor),
            patch.object(bad_cursor, "execute", return_value=bad_cursor),
        ):
            with self.assertRaisesRegex(DashboardExportError, "unexpected aggregate columns"):
                fetch_hourly_rows(connection, self.config)

    def test_snowflake_values_map_to_exact_dashboard_contract(self) -> None:
        snapshot = build_snapshot(
            self.config,
            self.stores,
            [mart_row()],
            exported_at=datetime(2026, 9, 30, 12, 30, tzinfo=UTC),
        )
        self.assertEqual(
            snapshot["metadata"],
            {
                "source": "Snowflake GEOPULSE.ANALYTICS_MARTS.FCT_STORE_CANNIBALIZATION "
                "+ store reference CSV",
                "refreshedAt": "2026-09-30T12:30:00Z",
                "timezone": "UTC",
                "retailTimezone": "Asia/Kolkata",
                "synthetic": False,
            },
        )
        self.assertEqual(len(snapshot["stores"]), 3)
        self.assertEqual(
            snapshot["flows"],
            [
                {
                    "scenarioId": "store_a|store_b|2026-09-30|morning_commute",
                    "existingStoreId": "store_a",
                    "candidateStoreId": "store_b",
                    "trafficDateLocal": "2026-09-30",
                    "daypart": "morning_commute",
                    "existingStoreUniqueVisitors": 10,
                    "candidateStoreUniqueVisitors": 4,
                    "sharedVisitors": 3,
                    "incrementalCandidateVisitors": 1,
                    "cannibalizationRate": 0.3,
                    "candidateOverlapRate": 0.75,
                    "candidateIncrementalReachRate": 0.25,
                }
            ],
        )
        text = json.dumps(snapshot)
        self.assertNotIn("device_id", text.lower())
        self.assertNotIn("password", text.lower())
        self.assertNotIn("store_pair_daypart_key", text.lower())

    def test_hourly_snapshot_is_sparse_sorted_and_contains_no_device_data(self) -> None:
        rows = [
            hourly_row(store_id="store_b", event_hour_local=9, unique_visitors=0, ping_count=0),
            hourly_row(event_hour_local=9, unique_visitors=3, ping_count=4),
            hourly_row(),
        ]
        snapshot = build_snapshot(self.config, self.stores, [mart_row()], hourly_rows=rows)
        self.assertEqual(
            snapshot["hourlyFootfall"],
            [
                {
                    "storeId": "store_a",
                    "trafficDateLocal": "2026-09-30",
                    "hourLocal": 8,
                    "uniqueVisitors": 10,
                    "pingCount": 12,
                },
                {
                    "storeId": "store_a",
                    "trafficDateLocal": "2026-09-30",
                    "hourLocal": 9,
                    "uniqueVisitors": 3,
                    "pingCount": 4,
                },
                {
                    "storeId": "store_b",
                    "trafficDateLocal": "2026-09-30",
                    "hourLocal": 9,
                    "uniqueVisitors": 0,
                    "pingCount": 0,
                },
            ],
        )
        self.assertEqual(len(snapshot["hourlyFootfall"]), len(rows))
        self.assertEqual(
            set(snapshot["hourlyFootfall"][0]),
            {"storeId", "trafficDateLocal", "hourLocal", "uniqueVisitors", "pingCount"},
        )
        self.assertIn(self.config.hourly_mart_table, snapshot["metadata"]["source"])
        self.assertNotIn("device_id", json.dumps(snapshot).lower())

    def test_hourly_date_timezone_store_hour_and_counts_are_validated(self) -> None:
        for change in (
            {"store_id": "unknown"},
            {"traffic_date_local": date(2026, 9, 29)},
            {"traffic_date_local": datetime(2026, 9, 30, tzinfo=UTC)},
            {"retail_timezone": "UTC"},
            {"event_hour_local": -1},
            {"event_hour_local": 24},
            {"event_hour_local": "8"},
            {"event_hour_local": True},
            {"unique_visitors": -1},
            {"unique_visitors": Decimal("1.5")},
            {"unique_visitors": Decimal("NaN")},
            {"unique_visitors": Decimal("9007199254740992")},
            {"ping_count": -1},
            {"ping_count": Decimal("1.5")},
            {"ping_count": Decimal("9007199254740992")},
            {"unique_visitors": 13},
        ):
            with self.subTest(change=change), self.assertRaises(DashboardExportError):
                build_snapshot(
                    self.config,
                    self.stores,
                    [mart_row()],
                    hourly_rows=[hourly_row(**change), hourly_row(store_id="store_b")],
                )

    def test_hourly_grain_and_flow_store_coverage_are_required(self) -> None:
        for rows in (
            [],
            [hourly_row()],
            [hourly_row(), hourly_row(), hourly_row(store_id="store_b")],
        ):
            with self.subTest(rows=rows), self.assertRaises(DashboardExportError):
                build_snapshot(self.config, self.stores, [mart_row()], hourly_rows=rows)

    def test_multiple_comparisons_are_sorted_and_have_unique_stable_scenarios(self) -> None:
        evening = mart_row(
            daypart="evening_commute",
            shared_visitors=Decimal("0"),
            incremental_candidate_visitors=Decimal("4"),
            cannibalization_rate=Decimal("0"),
            candidate_overlap_rate=Decimal("0"),
            candidate_incremental_reach_rate=Decimal("1"),
        )
        candidate = mart_row(candidate_store_id="store_c", candidate_store_status="candidate")
        first = build_snapshot(self.config, self.stores, [candidate, evening, mart_row()])
        second = build_snapshot(self.config, self.stores, [mart_row(), candidate, evening])
        first_ids = [flow["scenarioId"] for flow in first["flows"]]
        self.assertEqual(first_ids, [flow["scenarioId"] for flow in second["flows"]])
        self.assertEqual(len(set(first_ids)), 3)
        self.assertEqual(
            [flow["candidateStoreId"] for flow in first["flows"]], ["store_b", "store_b", "store_c"]
        )

    def test_duplicate_grain_and_empty_day_are_rejected(self) -> None:
        for rows in ([], [mart_row(), mart_row()]):
            with self.subTest(rows=rows), self.assertRaises(DashboardExportError):
                build_snapshot(self.config, self.stores, rows)

    def test_store_and_daypart_references_are_checked(self) -> None:
        for change in (
            {"existing_store_id": "missing"},
            {"candidate_store_id": "missing"},
            {"existing_store_id": "store_b"},
            {"candidate_store_id": "store_a"},
            {"candidate_store_status": "existing"},
            {"daypart": "unknown"},
        ):
            with self.subTest(change=change), self.assertRaises(DashboardExportError):
                build_snapshot(self.config, self.stores, [mart_row(**change)])

    def test_date_and_retail_timezone_are_checked_even_with_filtered_query(self) -> None:
        for change in (
            {"traffic_date_local": date(2026, 9, 29)},
            {"traffic_date_local": datetime(2026, 9, 30, tzinfo=UTC)},
            {"retail_timezone": "UTC"},
        ):
            with self.subTest(change=change), self.assertRaises(DashboardExportError):
                build_snapshot(self.config, self.stores, [mart_row(**change)])

    def test_count_and_rate_invariants_are_checked(self) -> None:
        for change in (
            {"existing_store_unique_visitors": 0},
            {"candidate_store_unique_visitors": -1},
            {"shared_visitors": 5},
            {"shared_visitors": Decimal("1.5")},
            {"incremental_candidate_visitors": 2},
            {"cannibalization_rate": Decimal("0.4")},
            {"candidate_overlap_rate": Decimal("-0.1")},
            {"candidate_incremental_reach_rate": Decimal("0.1")},
            {"existing_store_unique_visitors": Decimal("NaN")},
            {"existing_store_unique_visitors": Decimal("9007199254740992")},
        ):
            with self.subTest(change=change), self.assertRaises(DashboardExportError):
                build_snapshot(self.config, self.stores, [mart_row(**change)])

    def test_dbt_six_decimal_rounding_is_accepted(self) -> None:
        rounded = mart_row(
            existing_store_unique_visitors=3,
            shared_visitors=1,
            candidate_store_unique_visitors=3,
            incremental_candidate_visitors=2,
            cannibalization_rate=Decimal("0.333333"),
            candidate_overlap_rate=Decimal("0.333333"),
            candidate_incremental_reach_rate=Decimal("0.666667"),
        )
        snapshot = build_snapshot(self.config, self.stores, [rounded])
        self.assertEqual(snapshot["flows"][0]["cannibalizationRate"], 0.333333)

    def test_invalid_store_reference_is_rejected(self) -> None:
        invalid_cases = (
            "store_id,store_name,status,latitude,longitude,catchment_radius_m\n",
            STORES_CSV + "store_a,Duplicate,existing,0,0,500\n",
            STORES_CSV.replace("12.9756", "91"),
            STORES_CSV.replace("500\n", "0\n", 1),
            STORES_CSV.replace("store_b,Store B,proposed", "store_b,Store B,unknown"),
            STORES_CSV.replace("store_b,Store B", "store|b,Store B"),
            STORES_CSV.replace("store_id,store_name", "device_id,store_name"),
        )
        for content in invalid_cases:
            with self.subTest(content=content[:50]):
                self.stores_path.write_text(content, encoding="utf-8")
                with self.assertRaises(DashboardExportError):
                    read_stores(self.stores_path)

    def test_connection_settings_use_mart_schema_and_support_key_auth(self) -> None:
        environment = {
            "DBT_SNOWFLAKE_ACCOUNT": "account",
            "DBT_SNOWFLAKE_USER": "user",
            "DBT_SNOWFLAKE_WAREHOUSE": "warehouse",
            "DBT_SNOWFLAKE_PASSWORD": "secret-password",
            "DBT_SNOWFLAKE_SOURCE_SCHEMA": "invalid;source",
        }
        settings = read_dashboard_connection_settings(environment, self.config)
        self.assertEqual(settings["schema"], "ANALYTICS_MARTS")
        self.assertEqual(settings["password"], "secret-password")
        self.assertEqual(settings["role"], "GEOPULSE_TRANSFORMER")
        self.assertEqual(settings["session_parameters"]["QUERY_TAG"], "geopulse_dashboard_export")
        environment["GEOPULSE_DASHBOARD_SNOWFLAKE_ROLE"] = "geopulse_dashboard_reader"
        reader_settings = read_dashboard_connection_settings(environment, self.config)
        self.assertEqual(reader_settings["role"], "GEOPULSE_DASHBOARD_READER")
        environment["GEOPULSE_DASHBOARD_SNOWFLAKE_ROLE"] = "reader;DROP ROLE x"
        with self.assertRaises(DashboardExportError):
            read_dashboard_connection_settings(environment, self.config)
        environment.pop("GEOPULSE_DASHBOARD_SNOWFLAKE_ROLE")
        environment.pop("DBT_SNOWFLAKE_PASSWORD")
        environment["GEOPULSE_SNOWFLAKE_PRIVATE_KEY_FILE"] = "protected-key.p8"
        key_settings = read_dashboard_connection_settings(environment, self.config)
        self.assertEqual(key_settings["authenticator"], "SNOWFLAKE_JWT")
        self.assertNotIn("password", key_settings)

    def test_atomic_replace_retains_previous_file_on_failure_and_cleans_temp(self) -> None:
        self.output_path.parent.mkdir()
        self.output_path.write_text("old-good-snapshot", encoding="utf-8")
        snapshot = build_snapshot(self.config, self.stores, [mart_row()])
        with patch("geopulse.dashboard_export.os.replace", side_effect=OSError("disk failed")):
            with self.assertRaises(OSError):
                write_snapshot_atomically(self.output_path, snapshot)
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "old-good-snapshot")
        self.assertEqual(list(self.output_path.parent.glob("*.tmp")), [])
        write_snapshot_atomically(self.output_path, snapshot)
        self.assertEqual(json.loads(self.output_path.read_text(encoding="utf-8")), snapshot)

    def test_cli_success_writes_synthetic_snapshot_and_closes_session(self) -> None:
        connection = FakeConnection()
        output = StringIO()
        with (
            patch(
                "geopulse.dashboard_export.read_dashboard_connection_settings",
                return_value={},
            ),
            patch("geopulse.dashboard_export.connect_snowflake", return_value=connection),
            redirect_stdout(output),
        ):
            self.assertEqual(main(self._args()), 0)
        self.assertTrue(connection.closed)
        self.assertEqual(json.loads(output.getvalue())["status"], "exported")
        snapshot = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertIs(snapshot["metadata"]["synthetic"], True)
        self.assertEqual(len(snapshot["hourlyFootfall"]), 2)
        self.assertEqual(len(connection.statements), 2)
        self.assertEqual(json.loads(output.getvalue())["hourly_footfall_count"], 2)

    def test_cli_rejects_real_data_without_privacy_review_before_connect(self) -> None:
        self.output_path.parent.mkdir()
        self.output_path.write_text("old-good-snapshot", encoding="utf-8")
        error = StringIO()
        with (
            patch("geopulse.dashboard_export.connect_snowflake") as connect,
            redirect_stderr(error),
        ):
            self.assertEqual(main(self._args(synthetic=False)), 1)
        connect.assert_not_called()
        self.assertIn("synthetic-only", error.getvalue())
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "old-good-snapshot")

    def test_cli_bad_local_inputs_never_import_connector_or_mutate_output(self) -> None:
        self.output_path.parent.mkdir()
        self.output_path.write_text("old-good-snapshot", encoding="utf-8")
        self.stores_path.write_text("bad-reference", encoding="utf-8")
        error = StringIO()
        with (
            patch("geopulse.dashboard_export.connect_snowflake") as connect,
            redirect_stderr(error),
        ):
            self.assertEqual(main(self._args()), 1)
        connect.assert_not_called()
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "old-good-snapshot")
        self.assertIn("Store reference", error.getvalue())

    def test_cli_query_failure_preserves_file_closes_session_and_hides_secrets(self) -> None:
        self.output_path.parent.mkdir()
        self.output_path.write_text("old-good-snapshot", encoding="utf-8")
        connection = FakeConnection()
        connection.fail_query = True
        error = StringIO()
        with (
            patch("geopulse.dashboard_export.read_dashboard_connection_settings", return_value={}),
            patch("geopulse.dashboard_export.connect_snowflake", return_value=connection),
            redirect_stderr(error),
        ):
            self.assertEqual(main(self._args()), 1)
        self.assertTrue(connection.closed)
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "old-good-snapshot")
        self.assertIn("RuntimeError", error.getvalue())
        self.assertNotIn("secret-password", error.getvalue())

    def test_cli_missing_day_preserves_previous_snapshot(self) -> None:
        self.output_path.parent.mkdir()
        self.output_path.write_text("old-good-snapshot", encoding="utf-8")
        connection = FakeConnection([])
        with (
            patch("geopulse.dashboard_export.read_dashboard_connection_settings", return_value={}),
            patch("geopulse.dashboard_export.connect_snowflake", return_value=connection),
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(main(self._args()), 1)
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "old-good-snapshot")
        self.assertTrue(connection.closed)

    def test_cli_missing_hourly_coverage_preserves_previous_snapshot(self) -> None:
        self.output_path.parent.mkdir()
        self.output_path.write_text("old-good-snapshot", encoding="utf-8")
        connection = FakeConnection(hourly_rows=[hourly_row()])
        with (
            patch("geopulse.dashboard_export.read_dashboard_connection_settings", return_value={}),
            patch("geopulse.dashboard_export.connect_snowflake", return_value=connection),
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(main(self._args()), 1)
        self.assertEqual(self.output_path.read_text(encoding="utf-8"), "old-good-snapshot")
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
