from __future__ import annotations

import csv
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.spatial import SpatialJoinConfig, build_spark_session
from geopulse.zoning import (
    ZoningOverlayConfig,
    build_zoning_frames,
    validate_zoning_metrics,
    zone_schema,
)

ROOT = Path(__file__).resolve().parents[1]
ZONES = ROOT / "data" / "reference" / "synthetic_commercial_zones.csv"
SPATIAL_DEPENDENCIES_AVAILABLE = all(
    importlib.util.find_spec(name) is not None for name in ("pyspark", "sedona")
)


def valid_metrics() -> dict[str, int]:
    return {
        "raw_ping_rows": 3,
        "valid_ping_rows": 3,
        "rejected_ping_rows": 0,
        "raw_zone_rows": 3,
        "valid_zone_rows": 3,
        "rejected_zone_rows": 0,
        "matched_ping_zone_rows": 2,
        "matched_unique_devices": 2,
    }


class ZoningContractTests(unittest.TestCase):
    def test_reference_polygons_are_explicitly_synthetic(self) -> None:
        with ZONES.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({row["zone_id"] for row in rows}), 3)
        self.assertTrue(all(row["source_label"] == "synthetic" for row in rows))
        self.assertTrue(all(row["zone_id"].startswith("synthetic_zone_") for row in rows))
        self.assertTrue(all(row["polygon_wkt"].startswith("POLYGON ((") for row in rows))

    def test_config_requires_exact_expected_volume_and_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected_ping_rows"):
            ZoningOverlayConfig("pings", "zones", "output", 0)
        with self.assertRaisesRegex(ValueError, "zones_path"):
            ZoningOverlayConfig("pings", "", "output", 3)
        with self.assertRaisesRegex(ValueError, "shuffle_partitions"):
            ZoningOverlayConfig("pings", "zones", "output", 3, shuffle_partitions=0)

    def test_quality_gate_reconciles_counts_and_rejects_bad_synthetic_input(self) -> None:
        validate_zoning_metrics(valid_metrics(), 3)
        bad = valid_metrics()
        bad["rejected_zone_rows"] = 1
        bad["valid_zone_rows"] = 2
        with self.assertRaisesRegex(ValueError, "rejected pings or zones"):
            validate_zoning_metrics(bad, 3)
        bad = valid_metrics()
        bad["matched_ping_zone_rows"] = 0
        bad["matched_unique_devices"] = 0
        with self.assertRaisesRegex(ValueError, "no valid zones or spatial matches"):
            validate_zoning_metrics(bad, 3)
        with self.assertRaisesRegex(ValueError, "raw ping count differs"):
            validate_zoning_metrics(valid_metrics(), 4)


@unittest.skipUnless(
    SPATIAL_DEPENDENCIES_AVAILABLE,
    "install the spatial extra to run Apache Sedona zoning integration tests",
)
class SedonaZoningIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spark = build_spark_session(
            SpatialJoinConfig(
                "unused", str(ZONES), "unused", master="local[2]", shuffle_partitions=2
            )
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.spark.stop()

    def test_real_sedona_join_matches_only_synthetic_commercial_polygons(self) -> None:
        pings = self.spark.createDataFrame(
            [
                ("dev_mg", "2026-09-22T08:00:00+05:30", 12.9756, 77.6066, 5.0, "work"),
                ("dev_indira", "2026-09-22T08:00:00+05:30", 12.9784, 77.6408, 5.0, "work"),
                ("dev_outside", "2026-09-22T08:00:00+05:30", 12.99, 77.70, 5.0, "work"),
            ],
            "device_id string, event_ts string, latitude double, longitude double, "
            "accuracy_m double, activity_type string",
        )
        zones = (
            self.spark.read.options(header=True, mode="PERMISSIVE")
            .schema(zone_schema())
            .csv(str(ZONES))
        )
        frames = build_zoning_frames(pings, zones)
        matches = frames.matches.select("device_id", "zone_id", "source_label").collect()

        self.assertEqual(
            {(row.device_id, row.zone_id) for row in matches},
            {
                ("dev_mg", "synthetic_zone_mg_road"),
                ("dev_indira", "synthetic_zone_indiranagar"),
            },
        )
        self.assertTrue(all(row.source_label == "synthetic" for row in matches))
        self.assertEqual(frames.valid_zones.count(), 3)
        self.assertEqual(frames.rejected_zones.count(), 0)
        self.assertEqual(frames.rejected_pings.count(), 0)

    def test_non_synthetic_zone_cannot_enter_matches(self) -> None:
        pings = self.spark.createDataFrame(
            [("dev", "2026-09-22T08:00:00+05:30", 12.9756, 77.6066, 5.0, "work")],
            "device_id string, event_ts string, latitude double, longitude double, "
            "accuracy_m double, activity_type string",
        )
        zones = self.spark.createDataFrame(
            [
                (
                    "official_claim",
                    "Unverified official zone",
                    "retail_commercial",
                    "POLYGON ((77.60 12.97, 77.61 12.97, 77.61 12.98, 77.60 12.98, 77.60 12.97))",
                    "official",
                )
            ],
            zone_schema(),
        )
        frames = build_zoning_frames(pings, zones)
        self.assertEqual(frames.matches.count(), 0)
        self.assertEqual(
            frames.rejected_zones.first().rejection_reason, "non_synthetic_zone_source"
        )


if __name__ == "__main__":
    unittest.main()
