"""Keep the committed synthetic H3 map consistent with its raw ping fixture."""

from __future__ import annotations

import csv
import json
import unittest
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_PINGS = ROOT / "seeds" / "mobile_pings.csv"
STORE_MATCHES = ROOT / "seeds" / "ping_store_matches.csv"
DASHBOARD = ROOT / "dashboard" / "public" / "data" / "geopulse-dashboard.json"
KOLKATA_OFFSET = timedelta(hours=5, minutes=30)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class H3FixtureTests(unittest.TestCase):
    def test_raw_fixture_covers_each_distinct_catchment_ping_once(self) -> None:
        raw = _read_csv(RAW_PINGS)
        matches = _read_csv(STORE_MATCHES)
        raw_by_event = {(row["device_id"], row["event_ts"]): row for row in raw}
        self.assertEqual(
            len(raw_by_event), len(raw), "Raw ping fixture must have one event per key"
        )

        for match in matches:
            key = (match["device_id"], match["event_ts"])
            with self.subTest(event=key):
                self.assertIn(key, raw_by_event)
                source = raw_by_event[key]
                self.assertEqual(float(source["latitude"]), float(match["ping_latitude"]))
                self.assertEqual(float(source["longitude"]), float(match["ping_longitude"]))

        # The citywide raw feed may additionally include pings outside all catchments.
        matched_events = {(match["device_id"], match["event_ts"]) for match in matches}
        self.assertGreater(len(raw_by_event), len(matched_events))

    def test_dashboard_h3_rows_reconcile_to_local_day_raw_pings(self) -> None:
        snapshot = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        self.assertTrue(snapshot["metadata"]["synthetic"])
        flow_dates = {flow["trafficDateLocal"] for flow in snapshot["flows"]}
        self.assertEqual(flow_dates, {"2026-09-22"})

        observed = {}
        for row in snapshot["h3Footfall"]:
            self.assertEqual(
                set(row),
                {
                    "hexId",
                    "h3Resolution",
                    "trafficDateLocal",
                    "hourLocal",
                    "uniqueVisitors",
                    "pingCount",
                },
            )
            self.assertEqual(row["h3Resolution"], 8)
            key = (row["hexId"], row["trafficDateLocal"], row["hourLocal"])
            self.assertNotIn(key, observed)
            observed[key] = (row["uniqueVisitors"], row["pingCount"])

        devices: dict[tuple[str, str, int], set[str]] = defaultdict(set)
        pings: dict[tuple[str, str, int], int] = defaultdict(int)
        for row in _read_csv(RAW_PINGS):
            local_time = datetime.fromisoformat(row["event_ts"]) + KOLKATA_OFFSET
            local_date = local_time.date().isoformat()
            if local_date not in flow_dates:
                continue
            key = (row["hex_id"], local_date, local_time.hour)
            devices[key].add(row["device_id"])
            pings[key] += 1

        expected = {key: (len(devices[key]), count) for key, count in pings.items()}
        self.assertEqual(observed, expected)


if __name__ == "__main__":
    unittest.main()
