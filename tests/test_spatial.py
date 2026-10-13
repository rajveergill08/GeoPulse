from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.quality import (
    BATCH_SUCCESS_MARKER,
    SpatialQualityPolicy,
    validate_spatial_output,
)
from geopulse.spatial import (
    DEFAULT_MAVEN_PACKAGES,
    GEOTOOLS_WRAPPER_VERSION,
    SEDONA_VERSION,
    SPARK_VERSION,
    SpatialFrames,
    SpatialJoinConfig,
    _invalidate_batch_marker,
    _mark_batch_complete,
    _partition_matches_for_write,
    _write_outputs,
    build_spark_session,
    build_spatial_frames,
)

SPATIAL_DEPENDENCIES_AVAILABLE = all(
    importlib.util.find_spec(module_name) is not None for module_name in ("pyspark", "sedona")
)


class SpatialJoinConfigTests(unittest.TestCase):
    def test_runtime_versions_are_pinned_and_aligned(self) -> None:
        self.assertEqual(SEDONA_VERSION, "1.9.0")
        self.assertEqual(SPARK_VERSION, "4.0.4")
        self.assertEqual(GEOTOOLS_WRAPPER_VERSION, "1.9.0-33.5")
        self.assertIn("sedona-spark-shaded-4.0_2.13:1.9.0", DEFAULT_MAVEN_PACKAGES)
        self.assertIn("geotools-wrapper:1.9.0-33.5", DEFAULT_MAVEN_PACKAGES)

    def test_config_rejects_invalid_runtime_options(self) -> None:
        with self.assertRaisesRegex(ValueError, "shuffle_partitions"):
            SpatialJoinConfig("pings.csv", "stores.csv", "output", shuffle_partitions=0)
        with self.assertRaisesRegex(ValueError, "write_mode"):
            SpatialJoinConfig("pings.csv", "stores.csv", "output", write_mode="replace")

    def test_match_write_uses_hour_and_device_to_avoid_single_date_partition(self) -> None:
        matches = Mock()

        result = _partition_matches_for_write(matches, 16)

        self.assertIs(result, matches.repartitionByRange.return_value)
        matches.repartitionByRange.assert_called_once_with(
            16, "event_date", "event_hour_utc", "device_id"
        )

    def test_batch_marker_uses_spark_filesystem_and_deletes_only_existing_file(self) -> None:
        spark = Mock()
        marker = spark.sparkContext._jvm.org.apache.hadoop.fs.Path.return_value
        filesystem = marker.getFileSystem.return_value
        filesystem.exists.return_value = True
        filesystem.getFileStatus.return_value.isFile.return_value = True
        filesystem.delete.return_value = True

        _invalidate_batch_marker(spark, "s3a://example-bucket/batch")
        spark.sparkContext._jvm.org.apache.hadoop.fs.Path.assert_called_with(
            f"s3a://example-bucket/batch/{BATCH_SUCCESS_MARKER}"
        )
        filesystem.delete.assert_called_once_with(marker, False)
        _mark_batch_complete(spark, "s3a://example-bucket/batch")
        filesystem.create.assert_called_once_with(marker, False)
        filesystem.create.return_value.close.assert_called_once_with()

        filesystem.delete.reset_mock()
        filesystem.exists.return_value = False
        _invalidate_batch_marker(spark, "s3a://example-bucket/batch")
        filesystem.delete.assert_not_called()

    def test_batch_marker_rejects_unexpected_directory_or_failed_delete(self) -> None:
        spark = Mock()
        marker = spark.sparkContext._jvm.org.apache.hadoop.fs.Path.return_value
        filesystem = marker.getFileSystem.return_value
        filesystem.exists.return_value = True
        filesystem.getFileStatus.return_value.isFile.return_value = False

        with self.assertRaisesRegex(RuntimeError, "not a file"):
            _invalidate_batch_marker(spark, "output")
        filesystem.delete.assert_not_called()

        filesystem.getFileStatus.return_value.isFile.return_value = True
        filesystem.delete.return_value = False
        with self.assertRaisesRegex(RuntimeError, "Unable to invalidate"):
            _invalidate_batch_marker(spark, "output")

    def test_batch_marker_is_published_last_only_for_full_overwrite(self) -> None:
        spark = Mock()
        partitioned_matches = Mock()
        frames = SpatialFrames(*(Mock() for _ in range(6)))
        events: list[str] = []
        partitioned_matches.write.mode.return_value.partitionBy.return_value.parquet.side_effect = (
            lambda _: events.append("matches")
        )
        audit_frame = (
            spark.createDataFrame.return_value.withColumn.return_value.coalesce.return_value
        )
        audit_frame.write.mode.return_value.json.side_effect = lambda _: events.append("audit")
        with (
            patch("geopulse.spatial._require_spatial_dependencies", return_value=(Mock(), Mock())),
            patch(
                "geopulse.spatial._partition_matches_for_write",
                return_value=partitioned_matches,
            ),
            patch(
                "geopulse.spatial._invalidate_batch_marker",
                side_effect=lambda *_: events.append("invalidate"),
            ),
            patch(
                "geopulse.spatial._mark_batch_complete",
                side_effect=lambda *_: events.append("complete"),
            ),
        ):
            config = SpatialJoinConfig("pings", "stores", "output")
            _write_outputs(spark, config, frames, [("raw_ping_rows", 1)])
            self.assertEqual(events, ["invalidate", "matches", "audit", "complete"])

            events.clear()
            frames.rejected_stores.write.mode.return_value.parquet.side_effect = RuntimeError(
                "interrupted write"
            )
            with self.assertRaisesRegex(RuntimeError, "interrupted write"):
                _write_outputs(spark, config, frames, [("raw_ping_rows", 1)])
            self.assertEqual(events, ["invalidate", "matches"])

            events.clear()
            frames.rejected_stores.write.mode.return_value.parquet.side_effect = None
            append_config = SpatialJoinConfig("pings", "stores", "output", write_mode="append")
            _write_outputs(spark, append_config, frames, [("raw_ping_rows", 1)])
            self.assertEqual(events, ["invalidate", "matches", "audit"])


@unittest.skipUnless(
    SPATIAL_DEPENDENCIES_AVAILABLE,
    "install the spatial extra to run Apache Sedona integration tests",
)
class SedonaSpatialIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spark = build_spark_session(
            SpatialJoinConfig(
                pings_path="unused",
                stores_path="unused",
                output_path="unused",
                master="local[2]",
                shuffle_partitions=2,
            )
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.spark.stop()

    def test_point_in_metric_catchment_and_rejection_paths(self) -> None:
        pings = self.spark.createDataFrame(
            [
                ("dev_inside", "2026-09-20T08:00:00+05:30", 12.9780, 77.6066, 8.0, "work"),
                ("dev_outside", "2026-09-20T08:05:00+05:30", 12.9900, 77.6500, 9.0, "work"),
                ("dev_bad", "not-a-timestamp", 12.9756, 77.6066, 8.0, "work"),
            ],
            "device_id string, event_ts string, latitude double, longitude double, "
            "accuracy_m double, activity_type string",
        )
        stores = self.spark.createDataFrame(
            [
                ("store_a", "Store A", "existing", 12.9756, 77.6066, 500.0),
                ("store_bad", "Bad Store", "candidate", 95.0, 77.6066, 500.0),
            ],
            "store_id string, store_name string, status string, latitude double, "
            "longitude double, catchment_radius_m double",
        )

        frames = build_spatial_frames(pings, stores)
        matches = frames.matches.collect()
        catchments = frames.catchments.collect()
        rejected_pings = frames.rejected_pings.collect()
        rejected_stores = frames.rejected_stores.collect()

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].device_id, "dev_inside")
        self.assertEqual(matches[0].store_id, "store_a")
        self.assertGreater(matches[0].distance_to_store_m, 250.0)
        self.assertLess(matches[0].distance_to_store_m, 300.0)
        self.assertEqual(len(catchments), 1)
        self.assertTrue(catchments[0].catchment_wkt.startswith("POLYGON"))
        self.assertEqual(rejected_pings[0].rejection_reason, "invalid_event_timestamp")
        self.assertEqual(rejected_stores[0].rejection_reason, "invalid_latitude")

    def test_match_write_distributes_one_hour_without_changing_parquet_layout(self) -> None:
        from pyspark.sql import functions

        matches = self.spark.createDataFrame(
            [(f"device_{index:03d}", date(2026, 9, 20), 8) for index in range(96)],
            "device_id string, event_date date, event_hour_utc int",
        )
        distributed = _partition_matches_for_write(matches, 4)
        occupied_partitions = distributed.select(functions.spark_partition_id()).distinct().count()
        self.assertGreater(occupied_partitions, 1)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matches"
            distributed.write.partitionBy("event_date", "event_hour_utc").parquet(str(output))
            hour_directory = output / "event_date=2026-09-20" / "event_hour_utc=8"
            self.assertGreater(len(list(hour_directory.glob("*.parquet"))), 1)
            self.assertEqual(self.spark.read.parquet(str(output)).count(), 96)

    def test_batch_marker_round_trip_on_hadoop_local_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _mark_batch_complete(self.spark, directory)
            marker = Path(directory) / BATCH_SUCCESS_MARKER
            self.assertTrue(marker.is_file())
            _invalidate_batch_marker(self.spark, directory)
            self.assertFalse(marker.exists())

    def test_complete_spark_write_passes_spatial_quality_gate(self) -> None:
        pings = self.spark.createDataFrame(
            [("dev_inside", "2026-09-20T08:00:00+05:30", 12.9756, 77.6066, 8.0, "work")],
            "device_id string, event_ts string, latitude double, longitude double, "
            "accuracy_m double, activity_type string",
        )
        stores = self.spark.createDataFrame(
            [("store_a", "Store A", "existing", 12.9756, 77.6066, 500.0)],
            "store_id string, store_name string, status string, latitude double, "
            "longitude double, catchment_radius_m double",
        )
        frames = build_spatial_frames(pings, stores)
        metrics = [
            ("raw_ping_rows", 1),
            ("valid_ping_rows", 1),
            ("rejected_ping_rows", 0),
            ("raw_store_rows", 1),
            ("valid_store_rows", 1),
            ("rejected_store_rows", 0),
            ("matched_ping_store_rows", 1),
            ("matched_unique_devices", 1),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "batch"
            config = SpatialJoinConfig("unused", "unused", str(output), shuffle_partitions=2)
            _write_outputs(self.spark, config, frames, metrics)

            for marker in (
                output / BATCH_SUCCESS_MARKER,
                output / "audit" / "_SUCCESS",
                output / "matches" / "_SUCCESS",
            ):
                self.assertTrue(marker.is_file(), marker)
            report = validate_spatial_output(
                output / "audit", output / "matches", SpatialQualityPolicy(expected_ping_rows=1)
            )
            self.assertEqual(report.metrics["matched_ping_store_rows"], 1)


if __name__ == "__main__":
    unittest.main()
