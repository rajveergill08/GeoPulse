from __future__ import annotations

import csv
import gzip
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.synthetic import BENGALURU, GeneratorConfig, iter_pings, write_pings_csv


class GeneratorConfigTests(unittest.TestCase):
    def test_expected_rows_is_exact(self) -> None:
        config = GeneratorConfig(
            devices=3,
            days=2,
            interval_minutes=60,
            start_date=date(2026, 9, 19),
        )
        self.assertEqual(config.expected_rows, 144)

    def test_interval_must_evenly_partition_a_day(self) -> None:
        with self.assertRaisesRegex(ValueError, "divisor of 1440"):
            GeneratorConfig(
                devices=1,
                days=1,
                interval_minutes=17,
                start_date=date(2026, 9, 19),
            )


class SyntheticPingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = GeneratorConfig(
            devices=2,
            days=1,
            interval_minutes=60,
            start_date=date(2026, 9, 19),
            seed=7,
        )

    def test_generation_is_reproducible(self) -> None:
        first_run = list(iter_pings(self.config))
        second_run = list(iter_pings(self.config))
        self.assertEqual(first_run, second_run)

    def test_rows_are_anonymous_bounded_and_timezone_aware(self) -> None:
        pings = list(iter_pings(self.config))
        device_ids = {ping.device_id for ping in pings}

        self.assertEqual(len(pings), self.config.expected_rows)
        self.assertEqual(len(device_ids), self.config.devices)
        self.assertTrue(all(device_id.startswith("dev_") for device_id in device_ids))
        self.assertTrue(all(len(device_id) == 24 for device_id in device_ids))

        for ping in pings:
            self.assertGreaterEqual(ping.latitude, BENGALURU.min_latitude)
            self.assertLessEqual(ping.latitude, BENGALURU.max_latitude)
            self.assertGreaterEqual(ping.longitude, BENGALURU.min_longitude)
            self.assertLessEqual(ping.longitude, BENGALURU.max_longitude)
            self.assertIsNotNone(ping.event_ts.utcoffset())
            self.assertGreaterEqual(ping.accuracy_m, 5.0)
            self.assertLessEqual(ping.accuracy_m, 35.0)

    def test_weekend_pattern_contains_retail_movement(self) -> None:
        activities = {ping.activity_type for ping in iter_pings(self.config)}
        self.assertTrue({"home", "leisure_trip", "retail", "return_home"} <= activities)

    def test_weekday_pattern_contains_commuter_movement(self) -> None:
        weekday_config = GeneratorConfig(
            devices=1,
            days=1,
            interval_minutes=15,
            start_date=date(2026, 9, 21),
            seed=7,
        )
        activities = {ping.activity_type for ping in iter_pings(weekday_config)}
        self.assertTrue(
            {
                "home",
                "morning_commute",
                "work",
                "evening_commute",
                "retail",
                "return_home",
            }
            <= activities
        )

    def test_anonymization_salt_changes_identifiers(self) -> None:
        alternate_config = GeneratorConfig(
            devices=self.config.devices,
            days=self.config.days,
            interval_minutes=self.config.interval_minutes,
            start_date=self.config.start_date,
            seed=self.config.seed,
            anonymization_salt="alternate-synthetic-salt",
        )
        original_id = next(iter_pings(self.config)).device_id
        alternate_id = next(iter_pings(alternate_config)).device_id
        self.assertNotEqual(original_id, alternate_id)

    def test_gzip_writer_preserves_contract_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "pings.csv.gz"
            row_count = write_pings_csv(self.config, output_path)

            with gzip.open(output_path, mode="rt", encoding="utf-8", newline="") as source:
                rows = list(csv.DictReader(source))

        self.assertEqual(row_count, self.config.expected_rows)
        self.assertEqual(len(rows), self.config.expected_rows)
        self.assertEqual(
            tuple(rows[0]),
            (
                "device_id",
                "event_ts",
                "latitude",
                "longitude",
                "accuracy_m",
                "activity_type",
            ),
        )


if __name__ == "__main__":
    unittest.main()
