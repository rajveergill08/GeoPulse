"""Validate and publish one synthetic retail-day CSV batch to Snowflake RAW."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from geopulse.orchestration import PIPELINE_TIMEZONE
from geopulse.synthetic import CSV_FIELDS
from geopulse.warehouse import (
    WarehouseLoadError,
    connect_snowflake,
)
from geopulse.warehouse import (
    read_connection_settings as read_spatial_connection_settings,
)

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
RETAIL_OFFSET = timezone(timedelta(hours=5, minutes=30), name=PIPELINE_TIMEZONE)
RAW_COLUMNS = (
    "device_id",
    "event_ts_raw",
    "latitude_raw",
    "longitude_raw",
    "accuracy_m_raw",
    "activity_type",
)


class RawWarehouseError(ValueError):
    """A raw mobility batch could not be safely validated or published."""


def _identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise RawWarehouseError("Snowflake database/schema must be simple unquoted identifiers")
    return value.upper()


@dataclass(frozen=True)
class RawBatchConfig:
    """Input, expected cardinality, and target for one Asia/Kolkata calendar day."""

    run_date: date
    pings_path: Path
    expected_ping_rows: int
    expected_devices: int
    database: str = "GEOPULSE"
    schema: str = "RAW"

    def __post_init__(self) -> None:
        if not isinstance(self.run_date, date) or isinstance(self.run_date, datetime):
            raise RawWarehouseError("run_date must be a calendar date")
        for name in ("expected_ping_rows", "expected_devices"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise RawWarehouseError(f"{name} must be a positive integer")
        if self.expected_devices > self.expected_ping_rows:
            raise RawWarehouseError("expected_devices cannot exceed expected_ping_rows")
        object.__setattr__(self, "database", _identifier(self.database))
        schema = _identifier(self.schema)
        if schema != "RAW":
            raise RawWarehouseError("Raw mobility batches must target the RAW schema")
        object.__setattr__(self, "schema", schema)
        path = Path(self.pings_path).expanduser().resolve()
        if not (path.name.lower().endswith(".csv") or path.name.lower().endswith(".csv.gz")):
            raise RawWarehouseError("pings must be a .csv or .csv.gz file")
        object.__setattr__(self, "pings_path", path)

    @property
    def target_table(self) -> str:
        return f"{self.database}.{self.schema}.MOBILE_PINGS"

    @property
    def utc_window(self) -> tuple[datetime, datetime]:
        """Aware UTC bounds for a local retail day, including only the start instant."""

        local_start = datetime.combine(self.run_date, time.min, tzinfo=RETAIL_OFFSET)
        local_end = datetime.combine(
            self.run_date + timedelta(days=1), time.min, tzinfo=RETAIL_OFFSET
        )
        return local_start.astimezone(UTC), local_end.astimezone(UTC)

    @property
    def compression(self) -> str:
        return "GZIP" if self.pings_path.name.lower().endswith(".csv.gz") else "NONE"


@dataclass(frozen=True)
class RawLoadPlan:
    config: RawBatchConfig
    ping_rows: int
    unique_devices: int

    def as_dict(self) -> dict[str, Any]:
        start, end = self.config.utc_window
        return {
            "status": "validated",
            "run_date_local": self.config.run_date.isoformat(),
            "retail_timezone": PIPELINE_TIMEZONE,
            "utc_start_inclusive": start.isoformat().replace("+00:00", "Z"),
            "utc_end_exclusive": end.isoformat().replace("+00:00", "Z"),
            "target_table": self.config.target_table,
            "ping_rows": self.ping_rows,
            "unique_devices": self.unique_devices,
            "compression": self.config.compression,
        }


def _validate_ping(row: list[str], row_number: int, config: RawBatchConfig) -> None:
    """Check one CSV record without retaining its location or identifying fields."""

    if len(row) != len(CSV_FIELDS):
        raise RawWarehouseError(f"CSV row {row_number} does not contain six fields")
    if not row[0].strip() or not row[5].strip():
        raise RawWarehouseError(f"CSV row {row_number} has a blank device or activity")
    try:
        event_ts = datetime.fromisoformat(row[1])
    except ValueError as exc:
        raise RawWarehouseError(f"CSV row {row_number} has an invalid ISO timestamp") from exc
    if event_ts.tzinfo is None or event_ts.utcoffset() != RETAIL_OFFSET.utcoffset(None):
        raise RawWarehouseError(f"CSV row {row_number} needs an Asia/Kolkata timestamp offset")
    start, end = config.utc_window
    if not start <= event_ts.astimezone(UTC) < end:
        raise RawWarehouseError(f"CSV row {row_number} is outside the requested retail day")
    try:
        latitude, longitude, accuracy_m = (float(value) for value in row[2:5])
    except ValueError as exc:
        raise RawWarehouseError(
            f"CSV row {row_number} has a nonnumeric coordinate/accuracy"
        ) from exc
    if (
        not math.isfinite(latitude)
        or not -90 <= latitude <= 90
        or not math.isfinite(longitude)
        or not -180 <= longitude <= 180
        or not math.isfinite(accuracy_m)
        or accuracy_m <= 0
    ):
        raise RawWarehouseError(f"CSV row {row_number} has invalid coordinate/accuracy bounds")


def plan_raw_load(config: RawBatchConfig) -> RawLoadPlan:
    """Stream the entire input (including gzip CRC) before any connector is loaded."""

    if not config.pings_path.is_file():
        raise RawWarehouseError("Ping input is not a readable file")
    opener = gzip.open if config.compression == "GZIP" else Path.open
    devices: set[str] = set()
    ping_rows = 0
    try:
        with opener(config.pings_path, mode="rt", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            if tuple(next(reader, ())) != CSV_FIELDS:
                raise RawWarehouseError("Ping CSV header does not match the six expected fields")
            for row_number, row in enumerate(reader, start=2):
                _validate_ping(row, row_number, config)
                devices.add(row[0])
                ping_rows += 1
    except (OSError, UnicodeError, EOFError, csv.Error) as exc:
        # Underlying exceptions can include input contents or paths. Do not print them.
        raise RawWarehouseError("Ping CSV/GZIP could not be read completely") from exc
    if ping_rows != config.expected_ping_rows:
        raise RawWarehouseError(
            f"Ping row count is {ping_rows}; expected {config.expected_ping_rows}"
        )
    if len(devices) != config.expected_devices:
        raise RawWarehouseError(
            f"Unique device count is {len(devices)}; expected {config.expected_devices}"
        )
    return RawLoadPlan(config, ping_rows, len(devices))


def _result_rows(cursor: Any) -> list[dict[str, Any]]:
    names = [column[0].lower() for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _utc_bound(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _landing_validation_sql(landing: str) -> str:
    timestamp = "TRY_TO_TIMESTAMP_TZ(event_ts_raw)"
    latitude = "TRY_TO_DOUBLE(latitude_raw)"
    longitude = "TRY_TO_DOUBLE(longitude_raw)"
    accuracy = "TRY_TO_DOUBLE(accuracy_m_raw)"
    valid = " AND ".join(
        (
            "device_id IS NOT NULL AND TRIM(device_id) <> ''",
            "activity_type IS NOT NULL AND TRIM(activity_type) <> ''",
            f"{timestamp} IS NOT NULL",
            f"TO_CHAR({timestamp}, 'TZH:TZM') = '+05:30'",
            f"{timestamp} >= %s::TIMESTAMP_TZ",
            f"{timestamp} < %s::TIMESTAMP_TZ",
            f"{latitude} BETWEEN -90 AND 90",
            f"{longitude} BETWEEN -180 AND 180",
            f"{accuracy} > 0",
            # Snowflake's FLOAT is IEEE-754 double; its documented NaN ordering
            # makes an inclusive maximum-finite bound exclude both NaN and inf.
            f"{accuracy} <= 1.7976931348623157e308",
        )
    )
    return (
        "SELECT COUNT(*), COUNT(DISTINCT device_id), "
        f"COALESCE(COUNT_IF(NOT COALESCE({valid}, FALSE)), 0) FROM {landing}"
    )


def publish_raw_batch(connection: Any, plan: RawLoadPlan) -> dict[str, Any]:
    """Validate a temporary landing copy, then replace one UTC interval atomically.

    The caller owns and closes a dedicated, autocommit-enabled session. Its
    temporary stage/table disappear on close. The permanent target is untouched
    until the landing batch has passed all checks.
    """

    config = plan.config
    namespace = f"{config.database}.{config.schema}"
    attempt = uuid4().hex.upper()
    stage = f"{namespace}.GEOPULSE_RAW_{attempt}_STAGE"
    landing = f"{namespace}.GEOPULSE_RAW_{attempt}_PINGS"
    start, end = (_utc_bound(value) for value in config.utc_window)
    window = "event_ts >= %s::TIMESTAMP_TZ AND event_ts < %s::TIMESTAMP_TZ"
    with connection.cursor() as cursor:
        cursor.execute("ALTER SESSION SET TIMEZONE = 'UTC'")
        cursor.execute(f"CREATE TEMPORARY STAGE {stage}")
        columns = ", ".join(f"{name} VARCHAR" for name in RAW_COLUMNS)
        cursor.execute(f"CREATE TEMPORARY TABLE {landing} ({columns})")

        # A fresh session-local stage has exactly this file; PUT does not glob.
        file_uri = "file://" + config.pings_path.as_posix()
        escaped_uri = file_uri.replace("'", "''")
        cursor.execute(f"PUT '{escaped_uri}' @{stage} AUTO_COMPRESS = FALSE OVERWRITE = FALSE")
        uploaded = _result_rows(cursor)
        if len(uploaded) != 1 or uploaded[0].get("status") != "UPLOADED":
            raise RawWarehouseError("Ping file upload was not confirmed")

        # Direct COPY is deliberate: Snowflake ignores the field-count option
        # when a SELECT transformation is used as the COPY source.
        cursor.execute(
            f"COPY INTO {landing} FROM @{stage} "
            "FILE_FORMAT = (TYPE = CSV "
            f"COMPRESSION = {config.compression} "
            "FIELD_OPTIONALLY_ENCLOSED_BY = '\"' SKIP_HEADER = 1 "
            "EMPTY_FIELD_AS_NULL = FALSE ERROR_ON_COLUMN_COUNT_MISMATCH = TRUE) "
            "ON_ERROR = ABORT_STATEMENT"
        )
        copied = _result_rows(cursor)
        if (
            len(copied) != 1
            or copied[0].get("status") != "LOADED"
            or copied[0].get("rows_loaded") != plan.ping_rows
        ):
            raise RawWarehouseError("COPY results do not match the validated ping batch")

        cursor.execute(_landing_validation_sql(landing), (start, end))
        summary = cursor.fetchone()
        if summary is None or tuple(summary) != (plan.ping_rows, plan.unique_devices, 0):
            raise RawWarehouseError("Loaded pings fail count, type, offset, or retail-day checks")
        cursor.execute(
            f"SELECT COUNT(*) FROM (SELECT device_id, TO_TIMESTAMP_TZ(event_ts_raw) "
            f"FROM {landing} GROUP BY device_id, TO_TIMESTAMP_TZ(event_ts_raw) "
            "HAVING COUNT(*) > 1)"
        )
        duplicates = cursor.fetchone()
        if duplicates is None or duplicates[0] != 0:
            raise RawWarehouseError("Loaded pings contain duplicate device/timestamp keys")

        cursor.execute("BEGIN TRANSACTION")
        try:
            cursor.execute(f"DELETE FROM {config.target_table} WHERE {window}", (start, end))
            cursor.execute(
                f"INSERT INTO {config.target_table} "
                "(device_id, event_ts, latitude, longitude, accuracy_m, "
                "activity_type, location, source_filename) "
                "SELECT device_id, TO_TIMESTAMP_TZ(event_ts_raw), "
                "TRY_TO_DOUBLE(latitude_raw), TRY_TO_DOUBLE(longitude_raw), "
                "TRY_TO_DOUBLE(accuracy_m_raw), activity_type, "
                "ST_MAKEPOINT(TRY_TO_DOUBLE(longitude_raw), TRY_TO_DOUBLE(latitude_raw)), "
                f"%s FROM {landing}",
                (config.pings_path.name,),
            )
            cursor.execute(
                f"SELECT COUNT(*), COALESCE(COUNT_IF(location IS NULL), 0) "
                f"FROM {config.target_table} WHERE {window}",
                (start, end),
            )
            target_summary = cursor.fetchone()
            if target_summary is None or tuple(target_summary) != (plan.ping_rows, 0):
                raise RawWarehouseError("Target ping count or geography validation failed")
            cursor.execute("COMMIT")
        except BaseException:
            # Session close also rolls back if an interrupted connection cannot do so.
            try:
                cursor.execute("ROLLBACK")
            except Exception:
                pass
            raise

    return {
        "status": "published",
        "run_date_local": config.run_date.isoformat(),
        "target_table": config.target_table,
        "loaded_rows": plan.ping_rows,
        "unique_devices": plan.unique_devices,
        "uploaded_files": 1,
    }


def read_connection_settings(environment: Mapping[str, str]) -> dict[str, Any]:
    """Reuse the warehouse authentication policy, but select RAW and a distinct tag."""

    values = dict(environment)
    values["DBT_SNOWFLAKE_SOURCE_SCHEMA"] = "RAW"
    settings = read_spatial_connection_settings(values)
    settings["schema"] = "RAW"
    settings["session_parameters"] = {
        "TIMEZONE": "UTC",
        "QUERY_TAG": "geopulse_raw_publisher",
    }
    return settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish a validated retail-day raw ping batch.")
    parser.add_argument("--run-date", required=True, type=date.fromisoformat)
    parser.add_argument("--pings", required=True, type=Path)
    parser.add_argument("--expected-ping-rows", required=True, type=int)
    parser.add_argument("--expected-devices", required=True, type=int)
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate without Snowflake credentials"
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    connection = None
    try:
        config = RawBatchConfig(
            run_date=args.run_date,
            pings_path=args.pings,
            expected_ping_rows=args.expected_ping_rows,
            expected_devices=args.expected_devices,
            database=os.environ.get("DBT_SNOWFLAKE_DATABASE", "GEOPULSE"),
        )
        plan = plan_raw_load(config)
        if args.dry_run:
            result = plan.as_dict()
        else:
            settings = read_connection_settings(os.environ)
            connection = connect_snowflake(settings)
            result = publish_raw_batch(connection, plan)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (RawWarehouseError, WarehouseLoadError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        # Connector exceptions can contain authentication details or source rows.
        print(f"Snowflake raw publication failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
