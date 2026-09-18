"""Generate deterministic, anonymized synthetic mobility pings.

The generator is intentionally streaming: rows are yielded one at a time so a
large data set can be written without retaining every ping in memory.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Iterable, Iterator, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class GeoPoint:
    """A latitude/longitude coordinate in WGS84 order."""

    latitude: float
    longitude: float


@dataclass(frozen=True)
class CityBounds:
    """Rectangular bounds used to keep generated points inside a city."""

    name: str
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    centre: GeoPoint

    def clamp(self, point: GeoPoint) -> GeoPoint:
        return GeoPoint(
            latitude=min(max(point.latitude, self.min_latitude), self.max_latitude),
            longitude=min(max(point.longitude, self.min_longitude), self.max_longitude),
        )


BENGALURU = CityBounds(
    name="Bengaluru",
    min_latitude=12.8400,
    max_latitude=13.1200,
    min_longitude=77.4600,
    max_longitude=77.7600,
    centre=GeoPoint(latitude=12.9716, longitude=77.5946),
)


@dataclass(frozen=True)
class GeneratorConfig:
    """Configuration for a reproducible synthetic mobility run."""

    devices: int
    days: int
    interval_minutes: int
    start_date: date
    seed: int = 42
    timezone_name: str = "Asia/Kolkata"
    anonymization_salt: str = "geopulse-synthetic-v1"
    city: CityBounds = BENGALURU

    def __post_init__(self) -> None:
        if self.devices <= 0:
            raise ValueError("devices must be greater than zero")
        if self.days <= 0:
            raise ValueError("days must be greater than zero")
        if self.interval_minutes <= 0 or 1_440 % self.interval_minutes != 0:
            raise ValueError("interval_minutes must be a positive divisor of 1440")
        if not self.anonymization_salt:
            raise ValueError("anonymization_salt must not be empty")

    @property
    def expected_rows(self) -> int:
        """Return the exact number of pings produced by this configuration."""

        return self.devices * self.days * (1_440 // self.interval_minutes)


@dataclass(frozen=True)
class DeviceProfile:
    """Stable simulated routine for one anonymous device."""

    device_id: str
    home: GeoPoint
    work: GeoPoint
    retail: GeoPoint
    morning_departure: int
    morning_commute_minutes: int
    evening_departure: int
    retail_visit_minutes: int
    route_curve: float


@dataclass(frozen=True)
class MobilityPing:
    """One simulated GPS observation."""

    device_id: str
    event_ts: datetime
    latitude: float
    longitude: float
    accuracy_m: float
    activity_type: str

    def as_csv_row(self) -> dict[str, str]:
        return {
            "device_id": self.device_id,
            "event_ts": self.event_ts.isoformat(),
            "latitude": f"{self.latitude:.6f}",
            "longitude": f"{self.longitude:.6f}",
            "accuracy_m": f"{self.accuracy_m:.1f}",
            "activity_type": self.activity_type,
        }


CSV_FIELDS = (
    "device_id",
    "event_ts",
    "latitude",
    "longitude",
    "accuracy_m",
    "activity_type",
)


def _timezone_for(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        if name == "Asia/Kolkata":
            return timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
        raise ValueError(f"unknown timezone: {name}") from exc


def _derive_seed(seed: int, device_index: int) -> int:
    digest = hashlib.sha256(f"{seed}:{device_index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _anonymous_device_id(salt: str, device_index: int) -> str:
    digest = hashlib.sha256(f"{salt}:{device_index}".encode("utf-8")).hexdigest()
    return f"dev_{digest[:20]}"


def _sample_uniform_point(rng: random.Random, city: CityBounds) -> GeoPoint:
    return GeoPoint(
        latitude=rng.uniform(city.min_latitude, city.max_latitude),
        longitude=rng.uniform(city.min_longitude, city.max_longitude),
    )


def _sample_near(
    rng: random.Random,
    origin: GeoPoint,
    radius_km: float,
    city: CityBounds,
) -> GeoPoint:
    radius = radius_km * math.sqrt(rng.random())
    angle = rng.uniform(0.0, 2.0 * math.pi)
    latitude_delta = (radius * math.cos(angle)) / 111.32
    longitude_scale = max(math.cos(math.radians(origin.latitude)), 0.2)
    longitude_delta = (radius * math.sin(angle)) / (111.32 * longitude_scale)
    return city.clamp(
        GeoPoint(
            latitude=origin.latitude + latitude_delta,
            longitude=origin.longitude + longitude_delta,
        )
    )


def _build_profile(config: GeneratorConfig, device_index: int) -> tuple[DeviceProfile, random.Random]:
    rng = random.Random(_derive_seed(config.seed, device_index))
    home = _sample_uniform_point(rng, config.city)
    work = _sample_near(rng, config.city.centre, radius_km=8.0, city=config.city)

    # Most retail visits occur near a commute endpoint, while a smaller share
    # visits the central commercial district. This produces realistic overlap
    # for later catchment and cannibalization analysis.
    retail_anchor = home if rng.random() < 0.45 else work
    if rng.random() < 0.25:
        retail_anchor = config.city.centre
    retail = _sample_near(rng, retail_anchor, radius_km=3.0, city=config.city)

    profile = DeviceProfile(
        device_id=_anonymous_device_id(config.anonymization_salt, device_index),
        home=home,
        work=work,
        retail=retail,
        morning_departure=rng.randint(7 * 60, 8 * 60 + 30),
        morning_commute_minutes=rng.randint(35, 75),
        evening_departure=rng.randint(16 * 60 + 30, 18 * 60),
        retail_visit_minutes=rng.randint(45, 120),
        route_curve=rng.uniform(-0.012, 0.012),
    )
    return profile, rng


def _interpolate(start: GeoPoint, end: GeoPoint, progress: float, curve: float) -> GeoPoint:
    progress = min(max(progress, 0.0), 1.0)
    arc = math.sin(math.pi * progress) * curve
    return GeoPoint(
        latitude=start.latitude + (end.latitude - start.latitude) * progress + arc,
        longitude=end.longitude * progress + start.longitude * (1.0 - progress) - arc * 0.6,
    )


def _weekday_position(profile: DeviceProfile, minute: int) -> tuple[GeoPoint, str]:
    work_arrival = profile.morning_departure + profile.morning_commute_minutes
    retail_arrival = profile.evening_departure + 45
    retail_departure = retail_arrival + profile.retail_visit_minutes
    home_arrival = retail_departure + 60

    if minute < profile.morning_departure:
        return profile.home, "home"
    if minute < work_arrival:
        progress = (minute - profile.morning_departure) / profile.morning_commute_minutes
        return _interpolate(profile.home, profile.work, progress, profile.route_curve), "morning_commute"
    if minute < profile.evening_departure:
        return profile.work, "work"
    if minute < retail_arrival:
        progress = (minute - profile.evening_departure) / 45
        return _interpolate(profile.work, profile.retail, progress, -profile.route_curve), "evening_commute"
    if minute < retail_departure:
        return profile.retail, "retail"
    if minute < home_arrival:
        progress = (minute - retail_departure) / 60
        return _interpolate(profile.retail, profile.home, progress, profile.route_curve), "return_home"
    return profile.home, "home"


def _weekend_position(profile: DeviceProfile, minute: int) -> tuple[GeoPoint, str]:
    retail_departure = 10 * 60
    retail_arrival = 11 * 60
    return_departure = 17 * 60
    home_arrival = 18 * 60 + 30

    if minute < retail_departure:
        return profile.home, "home"
    if minute < retail_arrival:
        progress = (minute - retail_departure) / (retail_arrival - retail_departure)
        return _interpolate(profile.home, profile.retail, progress, profile.route_curve), "leisure_trip"
    if minute < return_departure:
        return profile.retail, "retail"
    if minute < home_arrival:
        progress = (minute - return_departure) / (home_arrival - return_departure)
        return _interpolate(profile.retail, profile.home, progress, -profile.route_curve), "return_home"
    return profile.home, "home"


def _add_gps_noise(
    point: GeoPoint,
    accuracy_m: float,
    rng: random.Random,
    city: CityBounds,
) -> GeoPoint:
    latitude_noise = rng.gauss(0.0, accuracy_m / 111_320.0)
    longitude_scale = max(math.cos(math.radians(point.latitude)), 0.2)
    longitude_noise = rng.gauss(0.0, accuracy_m / (111_320.0 * longitude_scale))
    return city.clamp(
        GeoPoint(
            latitude=point.latitude + latitude_noise,
            longitude=point.longitude + longitude_noise,
        )
    )


def iter_pings(config: GeneratorConfig) -> Iterator[MobilityPing]:
    """Yield deterministic mobility pings without materializing the full data set."""

    local_timezone = _timezone_for(config.timezone_name)
    first_timestamp = datetime.combine(config.start_date, time.min, tzinfo=local_timezone)

    for device_index in range(config.devices):
        profile, rng = _build_profile(config, device_index)
        for day_offset in range(config.days):
            current_day = config.start_date + timedelta(days=day_offset)
            for minute in range(0, 1_440, config.interval_minutes):
                if current_day.weekday() < 5:
                    base_point, activity_type = _weekday_position(profile, minute)
                else:
                    base_point, activity_type = _weekend_position(profile, minute)

                accuracy_m = rng.uniform(5.0, 35.0)
                noisy_point = _add_gps_noise(base_point, accuracy_m, rng, config.city)
                event_ts = first_timestamp + timedelta(days=day_offset, minutes=minute)
                yield MobilityPing(
                    device_id=profile.device_id,
                    event_ts=event_ts,
                    latitude=noisy_point.latitude,
                    longitude=noisy_point.longitude,
                    accuracy_m=accuracy_m,
                    activity_type=activity_type,
                )


def _open_output(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        return gzip.open(path, mode="wt", encoding="utf-8", newline="")
    return path.open(mode="w", encoding="utf-8", newline="")


def write_pings_csv(config: GeneratorConfig, output_path: Path | str) -> int:
    """Write pings to CSV or CSV.GZ and return the number of rows written."""

    destination = Path(output_path)
    row_count = 0
    with _open_output(destination) as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for ping in iter_pings(config):
            writer.writerow(ping.as_csv_row())
            row_count += 1

    if row_count != config.expected_rows:
        raise RuntimeError(
            f"row count mismatch: wrote {row_count}, expected {config.expected_rows}"
        )
    return row_count


def _parse_date(raw_value: str) -> date:
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate reproducible anonymized synthetic mobility pings."
    )
    parser.add_argument("--devices", type=int, default=1_000)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--interval-minutes", type=int, default=15)
    parser.add_argument("--start-date", type=_parse_date, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timezone", default="Asia/Kolkata")
    parser.add_argument("--anonymization-salt", default="geopulse-synthetic-v1")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = GeneratorConfig(
            devices=args.devices,
            days=args.days,
            interval_minutes=args.interval_minutes,
            start_date=args.start_date,
            seed=args.seed,
            timezone_name=args.timezone,
            anonymization_salt=args.anonymization_salt,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    rows_written = write_pings_csv(config, args.output)
    summary = {
        "city": config.city.name,
        "devices": config.devices,
        "days": config.days,
        "interval_minutes": config.interval_minutes,
        "rows_written": rows_written,
        "start_date": config.start_date.isoformat(),
        "timezone": config.timezone_name,
        "output": str(args.output.resolve()),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
