from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.quality import (
    SpatialQualityError,
    SpatialQualityPolicy,
    load_spatial_audit,
    main,
    validate_spatial_metrics,
    validate_spatial_output,
)

VALID_METRICS = {
    "raw_ping_rows": 100,
    "valid_ping_rows": 99,
    "rejected_ping_rows": 1,
    "raw_store_rows": 2,
    "valid_store_rows": 2,
    "rejected_store_rows": 0,
    "matched_ping_store_rows": 25,
    "matched_unique_devices": 20,
}


class SpatialQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.audit_path = self.root / "audit"
        self.matches_path = self.root / "matches"
        self.policy = SpatialQualityPolicy(
            expected_ping_rows=100,
            max_ping_rejection_rate=0.02,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_audit(
        self,
        records: list[tuple[str, object]],
        split_at: int | None = None,
    ) -> None:
        self.audit_path.mkdir(parents=True, exist_ok=True)
        split_index = len(records) if split_at is None else split_at
        chunks = (records[:split_index], records[split_index:])
        for index, chunk in enumerate(chunks):
            if not chunk:
                continue
            part_path = self.audit_path / f"part-{index:05d}.json"
            with part_path.open("w", encoding="utf-8") as handle:
                for metric, value in chunk:
                    handle.write(json.dumps({"metric": metric, "value": value}) + "\n")
        (self.audit_path / "_SUCCESS").write_text("ignored", encoding="utf-8")

    def _write_match_parquet(self) -> None:
        partition = self.matches_path / "event_date=2026-09-28" / "event_hour_utc=8"
        partition.mkdir(parents=True, exist_ok=True)
        (partition / "part-00000.parquet").write_bytes(b"PAR1\x00\x00\x00\x00PAR1")

    def test_valid_output_passes_with_partitioned_parquet(self) -> None:
        records = list(VALID_METRICS.items())
        self._write_audit(records, split_at=4)
        self._write_match_parquet()

        report = validate_spatial_output(self.audit_path, self.matches_path, self.policy)

        self.assertEqual(report.metrics, VALID_METRICS)
        self.assertAlmostEqual(report.ping_rejection_rate, 0.01)
        self.assertEqual(report.as_dict()["status"], "passed")

    def test_audit_requires_every_metric_exactly_once(self) -> None:
        records = list(VALID_METRICS.items())
        self._write_audit(records[:-1])

        with self.assertRaisesRegex(SpatialQualityError, "missing required metrics"):
            load_spatial_audit(self.audit_path)

        self.temporary_directory.cleanup()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.audit_path = self.root / "audit"
        self.matches_path = self.root / "matches"
        self._write_audit(records + [records[0]], split_at=len(records))

        with self.assertRaisesRegex(SpatialQualityError, "appears more than once"):
            load_spatial_audit(self.audit_path)

    def test_audit_rejects_malformed_and_invalid_values(self) -> None:
        self.audit_path.mkdir(parents=True)
        (self.audit_path / "part-00000.json").write_text("not-json\n", encoding="utf-8")
        with self.assertRaisesRegex(SpatialQualityError, "Invalid audit JSON"):
            load_spatial_audit(self.audit_path)

        (self.audit_path / "part-00000.json").write_text(
            json.dumps({"metric": "raw_ping_rows", "value": -1}) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(SpatialQualityError, "non-negative integer"):
            load_spatial_audit(self.audit_path)

    def test_metric_gate_rejects_wrong_volume_and_row_imbalances(self) -> None:
        cases = (
            (
                {**VALID_METRICS, "raw_ping_rows": 101, "valid_ping_rows": 100},
                "expected 100",
            ),
            (
                {**VALID_METRICS, "valid_ping_rows": 98},
                "ping rows do not reconcile",
            ),
            (
                {
                    **VALID_METRICS,
                    "raw_store_rows": 3,
                },
                "store rows do not reconcile",
            ),
        )

        for metrics, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(SpatialQualityError, message):
                    validate_spatial_metrics(metrics, self.policy)

    def test_metric_gate_reports_missing_or_invalid_metrics(self) -> None:
        missing = dict(VALID_METRICS)
        missing.pop("raw_ping_rows")
        with self.assertRaisesRegex(SpatialQualityError, "missing required values"):
            validate_spatial_metrics(missing, self.policy)

        with self.assertRaisesRegex(SpatialQualityError, "non-negative integer"):
            validate_spatial_metrics({**VALID_METRICS, "raw_ping_rows": True}, self.policy)

    def test_metric_gate_enforces_rejection_limits(self) -> None:
        with self.assertRaisesRegex(SpatialQualityError, "ping rejection rate exceeds"):
            validate_spatial_metrics(
                VALID_METRICS,
                SpatialQualityPolicy(
                    expected_ping_rows=100,
                    max_ping_rejection_rate=0.005,
                ),
            )

        rejected_store_metrics = {
            **VALID_METRICS,
            "valid_store_rows": 1,
            "rejected_store_rows": 1,
        }
        with self.assertRaisesRegex(SpatialQualityError, "rejected_store_rows exceeds"):
            validate_spatial_metrics(rejected_store_metrics, self.policy)

    def test_metric_gate_rejects_empty_or_impossible_matches(self) -> None:
        cases = (
            (
                {
                    **VALID_METRICS,
                    "matched_ping_store_rows": 0,
                    "matched_unique_devices": 0,
                },
                "matched_ping_store_rows must be greater than zero",
            ),
            (
                {**VALID_METRICS, "matched_unique_devices": 26},
                "cannot exceed matched_ping_store_rows",
            ),
            (
                {
                    **VALID_METRICS,
                    "matched_ping_store_rows": 120,
                    "matched_unique_devices": 100,
                },
                "cannot exceed valid_ping_rows",
            ),
            (
                {
                    **VALID_METRICS,
                    "valid_ping_rows": 90,
                    "rejected_ping_rows": 10,
                    "valid_store_rows": 1,
                    "raw_store_rows": 1,
                    "matched_ping_store_rows": 91,
                    "matched_unique_devices": 20,
                },
                "multiplied by valid_store_rows",
            ),
        )

        for metrics, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(SpatialQualityError, message):
                    validate_spatial_metrics(metrics, self.policy)

    def test_output_requires_a_recursive_parquet_part(self) -> None:
        self._write_audit(list(VALID_METRICS.items()))
        self.matches_path.mkdir()

        with self.assertRaisesRegex(SpatialQualityError, "contain no Parquet files"):
            validate_spatial_output(self.audit_path, self.matches_path, self.policy)

    def test_output_rejects_truncated_and_wrong_magic_parquet(self) -> None:
        self._write_audit(list(VALID_METRICS.items()))
        cases = (
            ("empty", b"", "truncated"),
            ("short", b"PAR1", "truncated"),
            ("wrong-magic", b"NOPE\x00\x00\x00\x00NOPE", "invalid Parquet magic"),
        )

        for name, payload, message in cases:
            with self.subTest(name=name):
                matches_path = self.root / f"matches-{name}"
                matches_path.mkdir()
                (matches_path / "part-00000.parquet").write_bytes(payload)
                with self.assertRaisesRegex(SpatialQualityError, message):
                    validate_spatial_output(self.audit_path, matches_path, self.policy)

    def test_cli_returns_structured_success_and_nonzero_failure(self) -> None:
        self._write_audit(list(VALID_METRICS.items()))
        self._write_match_parquet()
        arguments = [
            "--audit",
            str(self.audit_path),
            "--matches",
            str(self.matches_path),
            "--expected-ping-rows",
            "100",
            "--max-ping-rejection-rate",
            "0.02",
        ]

        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(arguments), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "passed")

        error = StringIO()
        with redirect_stderr(error):
            self.assertEqual(main([*arguments[:-3], "99"]), 1)
        self.assertIn("expected 99", error.getvalue())

    def test_policy_rejects_unsafe_thresholds(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected_ping_rows"):
            SpatialQualityPolicy(expected_ping_rows=0)
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            SpatialQualityPolicy(expected_ping_rows=1, max_ping_rejection_rate=1.1)
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            SpatialQualityPolicy(expected_ping_rows=1, max_rejected_store_rows=-1)


if __name__ == "__main__":
    unittest.main()
