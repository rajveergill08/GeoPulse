from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.quality import SpatialQualityReport
from geopulse.scale_verify import (
    ScaleVerificationConfig,
    ScaleVerificationError,
    _prepare_stores,
    _read_reference_stores,
    main,
    run_verification,
)


class ScaleVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.stores = self.root / "stores.csv"
        self.stores.write_text(
            "store_id,store_name,status,latitude,longitude,catchment_radius_m\n"
            "store_a,Store A,existing,12.9756,77.6066,500\n",
            encoding="utf-8",
        )
        self.output = self.root / "new-verification"

    def config(self, **changes: object) -> ScaleVerificationConfig:
        options = {
            "run_date": date(2026, 9, 22),
            "stores_path": self.stores,
            "output_path": self.output,
        }
        options.update(changes)
        return ScaleVerificationConfig(**options)

    def test_default_and_ten_million_row_plans_use_exact_generator_math(self) -> None:
        self.assertEqual(self.config().expected_ping_rows, 9_600)
        self.assertEqual(self.config().max_ping_rejection_rate, 0.0)
        self.assertEqual(self.config(devices=104_167).expected_ping_rows, 10_000_032)
        with self.assertRaisesRegex(ValueError, "positive divisor"):
            self.config(interval_minutes=17)
        with self.assertRaisesRegex(ValueError, "synthetic_stores"):
            self.config(synthetic_stores=100_001)

    def test_deterministic_store_grid_preserves_reference_and_reaches_5000(self) -> None:
        self.output.mkdir()
        reference = _read_reference_stores(self.stores)
        first = _prepare_stores(self.output, reference, 5_000).read_bytes()
        self.assertEqual(first, _prepare_stores(self.output, reference, 5_000).read_bytes())

        with (self.output / "benchmark_stores.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 5_000)
        self.assertEqual(rows[0]["store_id"], "store_a")
        self.assertEqual(rows[-1]["store_id"], "benchmark_store_004999")
        self.assertEqual(len({row["store_id"] for row in rows}), 5_000)
        self.assertTrue(all(row["catchment_radius_m"] == "500" for row in rows))

    def test_synthetic_store_count_below_reference_is_refused_before_writing(self) -> None:
        with self.stores.open("a", encoding="utf-8") as handle:
            handle.write("store_b,Store B,candidate,12.9719,77.6070,500\n")
        with self.assertRaisesRegex(ScaleVerificationError, "below 2 reference stores"):
            run_verification(self.config(synthetic_stores=1))
        self.assertFalse(self.output.exists())

    def test_existing_output_is_refused_without_touching_it(self) -> None:
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("user data", encoding="utf-8")

        with patch("geopulse.scale_verify.subprocess.run") as runner:
            with self.assertRaisesRegex(ScaleVerificationError, "already exists"):
                run_verification(self.config())
        runner.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user data")

    def test_success_runs_generator_spatial_and_quality_in_order(self) -> None:
        report = SpatialQualityReport(
            metrics={
                "raw_ping_rows": 9_600,
                "valid_ping_rows": 9_600,
                "rejected_ping_rows": 0,
                "raw_store_rows": 1,
                "valid_store_rows": 1,
                "rejected_store_rows": 0,
                "matched_ping_store_rows": 100,
                "matched_unique_devices": 10,
            },
            ping_rejection_rate=0.0,
            audit_path=str(self.output / "spatial" / "audit"),
            matches_path=str(self.output / "spatial" / "matches"),
        )
        with (
            patch(
                "geopulse.scale_verify.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0),
            ) as runner,
            patch(
                "geopulse.scale_verify._machine_context",
                return_value={"spark_peak_memory_measured": False},
            ),
            patch("geopulse.scale_verify.validate_spatial_output", return_value=report) as audit,
            redirect_stdout(io.StringIO()),
        ):
            evidence = run_verification(self.config())

        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["expected_ping_rows"], 9_600)
        self.assertEqual(
            [stage["name"] for stage in evidence["stages"]],
            ["generate", "spatial_join", "quality_gate"],
        )
        self.assertFalse(evidence["machine"]["spark_peak_memory_measured"])
        self.assertEqual(evidence["reference_store_rows"], 1)
        self.assertEqual(
            evidence["reference_stores_sha256"],
            hashlib.sha256(self.stores.read_bytes()).hexdigest(),
        )
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(
            [command[2] for command in commands],
            ["geopulse.synthetic", "geopulse.spatial", "geopulse.quality"],
        )
        self.assertIn("9600", commands[2])
        self.assertEqual(audit.call_count, 1)
        self.assertEqual(
            json.loads((self.output / "verification.json").read_text(encoding="utf-8")),
            evidence,
        )

    def test_failed_spatial_stage_keeps_failure_evidence_and_stops(self) -> None:
        with (
            patch(
                "geopulse.scale_verify.subprocess.run",
                side_effect=[
                    CompletedProcess(args=[], returncode=0),
                    CompletedProcess(args=[], returncode=7),
                ],
            ) as runner,
            patch(
                "geopulse.scale_verify._machine_context",
                return_value={"spark_peak_memory_measured": False},
            ),
            patch("geopulse.scale_verify.validate_spatial_output") as audit,
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(ScaleVerificationError, "spatial_join exited"):
                run_verification(self.config())

        evidence = json.loads((self.output / "verification.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["failed_stage"], "spatial_join")
        self.assertEqual([stage["return_code"] for stage in evidence["stages"]], [0, 7])
        self.assertEqual(runner.call_count, 2)
        audit.assert_not_called()

    def test_requested_polygons_must_match_the_spatial_audit(self) -> None:
        report = SpatialQualityReport(
            metrics={"raw_store_rows": 4, "valid_store_rows": 4},
            ping_rejection_rate=0.0,
            audit_path=str(self.output / "spatial" / "audit"),
            matches_path=str(self.output / "spatial" / "matches"),
        )
        with (
            patch(
                "geopulse.scale_verify._machine_context",
                return_value={"spark_peak_memory_measured": False},
            ),
            patch(
                "geopulse.scale_verify.subprocess.run",
                return_value=CompletedProcess(args=[], returncode=0),
            ),
            patch("geopulse.scale_verify.validate_spatial_output", return_value=report),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaisesRegex(ScaleVerificationError, "expected 5, raw 4, valid 4"):
                run_verification(self.config(synthetic_stores=5))

        evidence = json.loads((self.output / "verification.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["failed_stage"], "audit_recheck")
        self.assertEqual(evidence["expected_store_rows"], 5)
        self.assertEqual(
            evidence["spatial_stores_sha256"],
            hashlib.sha256((self.output / "benchmark_stores.csv").read_bytes()).hexdigest(),
        )

    def test_machine_context_failure_is_recorded_before_any_stage(self) -> None:
        with (
            patch(
                "geopulse.scale_verify._machine_context", side_effect=OSError("disk unavailable")
            ),
            patch("geopulse.scale_verify.subprocess.run") as runner,
        ):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                run_verification(self.config())

        evidence = json.loads((self.output / "verification.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["failed_stage"], "machine_context")
        runner.assert_not_called()

    def test_interrupt_marks_evidence_incomplete(self) -> None:
        with (
            patch(
                "geopulse.scale_verify._machine_context",
                return_value={"spark_peak_memory_measured": False},
            ),
            patch("geopulse.scale_verify.subprocess.run", side_effect=KeyboardInterrupt),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(KeyboardInterrupt):
                run_verification(self.config())

        evidence = json.loads((self.output / "verification.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["status"], "interrupted")
        self.assertEqual(evidence["failed_stage"], "generate")

    def test_plan_is_read_only_and_reports_commands(self) -> None:
        stdout = io.StringIO()
        with patch("geopulse.scale_verify.subprocess.run") as runner, redirect_stdout(stdout):
            result = main(
                [
                    "--run-date",
                    "2026-09-22",
                    "--stores",
                    str(self.stores),
                    "--output",
                    str(self.output),
                    "--synthetic-stores",
                    "5000",
                    "--plan",
                ]
            )
        plan = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(plan["status"], "planned_only")
        self.assertEqual(plan["expected_ping_rows"], 9_600)
        self.assertEqual(plan["synthetic_stores"], 5_000)
        self.assertEqual(plan["expected_store_rows"], 5_000)
        self.assertEqual(len(plan["commands"]), 3)
        self.assertEqual(
            plan["commands"][1][plan["commands"][1].index("--stores") + 1],
            str(self.output / "benchmark_stores.csv"),
        )
        self.assertFalse(self.output.exists())
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
