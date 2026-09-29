"""Publish one validated retail-day spatial batch to Snowflake atomically."""

from __future__ import annotations

import argparse
import json
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
from geopulse.quality import (
    SpatialQualityError,
    SpatialQualityPolicy,
    SpatialQualityReport,
    validate_spatial_output,
)

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
RETAIL_OFFSET = timezone(timedelta(hours=5, minutes=30), name=PIPELINE_TIMEZONE)
MATCH_COLUMNS = (
    "device_id",
    "event_ts",
    "ping_latitude",
    "ping_longitude",
    "accuracy_m",
    "activity_type",
    "store_id",
    "store_name",
    "store_status",
    "catchment_radius_m",
    "distance_to_store_m",
    "source_filename",
)


class WarehouseLoadError(ValueError):
    """A batch could not be validated or published safely."""


def _identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise WarehouseLoadError("Snowflake database/schema must be simple unquoted identifiers")
    return value.upper()


@dataclass(frozen=True)
class BatchLoadConfig:
    """Local input and target for a single Asia/Kolkata calendar day."""

    run_date: date
    matches_path: Path
    audit_path: Path
    policy: SpatialQualityPolicy
    database: str = "GEOPULSE"
    schema: str = "SPATIAL"

    def __post_init__(self) -> None:
        if not isinstance(self.run_date, date) or isinstance(self.run_date, datetime):
            raise WarehouseLoadError("run_date must be a calendar date")
        object.__setattr__(self, "database", _identifier(self.database))
        object.__setattr__(self, "schema", _identifier(self.schema))
        object.__setattr__(self, "matches_path", Path(self.matches_path).expanduser().resolve())
        object.__setattr__(self, "audit_path", Path(self.audit_path).expanduser().resolve())

    @property
    def target_table(self) -> str:
        return f"{self.database}.{self.schema}.PING_STORE_MATCHES"

    @property
    def utc_window(self) -> tuple[datetime, datetime]:
        """Return naive UTC bounds for the TIMESTAMP_NTZ source column."""

        local_start = datetime.combine(self.run_date, time.min, tzinfo=RETAIL_OFFSET)
        local_end = datetime.combine(
            self.run_date + timedelta(days=1), time.min, tzinfo=RETAIL_OFFSET
        )
        return (
            local_start.astimezone(UTC).replace(tzinfo=None),
            local_end.astimezone(UTC).replace(tzinfo=None),
        )


@dataclass(frozen=True)
class SpatialLoadPlan:
    config: BatchLoadConfig
    quality_report: SpatialQualityReport
    parquet_files: tuple[Path, ...]

    def as_dict(self) -> dict[str, Any]:
        start, end = self.config.utc_window
        return {
            "status": "validated",
            "run_date_local": self.config.run_date.isoformat(),
            "retail_timezone": PIPELINE_TIMEZONE,
            "utc_start_inclusive": start.isoformat() + "Z",
            "utc_end_exclusive": end.isoformat() + "Z",
            "target_table": self.config.target_table,
            "expected_match_rows": self.quality_report.metrics["matched_ping_store_rows"],
            "expected_unique_devices": self.quality_report.metrics["matched_unique_devices"],
            "file_count": len(self.parquet_files),
            "files": [
                path.relative_to(self.config.matches_path).as_posix() for path in self.parquet_files
            ],
        }


def plan_spatial_load(config: BatchLoadConfig) -> SpatialLoadPlan:
    """Validate local outputs before importing a connector or opening a session."""

    report = validate_spatial_output(config.audit_path, config.matches_path, config.policy)
    files = tuple(sorted(path for path in config.matches_path.rglob("*.parquet") if path.is_file()))
    return SpatialLoadPlan(config, report, files)


def _result_rows(cursor: Any) -> list[dict[str, Any]]:
    names = [column[0].lower() for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _copy_statement(landing_table: str, stage: str) -> str:
    fields = [
        "source.$1:device_id::VARCHAR",
        "source.$1:event_ts::TIMESTAMP_NTZ",
        "source.$1:ping_latitude::FLOAT",
        "source.$1:ping_longitude::FLOAT",
        "source.$1:accuracy_m::FLOAT",
        "source.$1:activity_type::VARCHAR",
        "source.$1:store_id::VARCHAR",
        "source.$1:store_name::VARCHAR",
        "source.$1:store_status::VARCHAR",
        "source.$1:catchment_radius_m::FLOAT",
        "source.$1:distance_to_store_m::FLOAT",
        "METADATA$FILENAME",
    ]
    return (
        f"COPY INTO {landing_table} ({', '.join(MATCH_COLUMNS)}) "
        f"FROM (SELECT {', '.join(fields)} FROM @{stage} source) "
        "FILE_FORMAT = (TYPE = PARQUET BINARY_AS_TEXT = FALSE "
        "USE_LOGICAL_TYPE = TRUE USE_VECTORIZED_SCANNER = FALSE) "
        "PATTERN = '.*[.]parquet' ON_ERROR = ABORT_STATEMENT"
    )


def publish_spatial_batch(connection: Any, plan: SpatialLoadPlan) -> dict[str, Any]:
    """Upload and validate a batch, then replace its UTC interval in one transaction.

    The caller supplies a dedicated session with autocommit enabled and closes it
    afterward. Temporary stage/table objects are removed when that session ends.
    Only the DELETE and INSERT modify the permanent target.
    """

    config = plan.config
    attempt_id = uuid4().hex.upper()
    namespace = f"{config.database}.{config.schema}"
    stage = f"{namespace}.GEOPULSE_LOAD_{attempt_id}_STAGE"
    landing = f"{namespace}.GEOPULSE_LOAD_{attempt_id}_MATCHES"
    expected_rows = plan.quality_report.metrics["matched_ping_store_rows"]
    expected_devices = plan.quality_report.metrics["matched_unique_devices"]
    start, end = (value.strftime("%Y-%m-%d %H:%M:%S") for value in config.utc_window)
    window = "event_ts >= %s::TIMESTAMP_NTZ AND event_ts < %s::TIMESTAMP_NTZ"

    with connection.cursor() as cursor:
        cursor.execute("ALTER SESSION SET TIMEZONE = 'UTC'")
        cursor.execute(f"CREATE TEMPORARY STAGE {stage}")
        cursor.execute(f"CREATE TEMPORARY TABLE {landing} LIKE {config.target_table}")
        for ordinal, path in enumerate(plan.parquet_files):
            # Each file gets its own directory: Spark basenames can repeat across partitions.
            file_uri = "file://" + path.as_posix()
            escaped_uri = file_uri.replace("'", "''")
            cursor.execute(
                f"PUT '{escaped_uri}' @{stage}/file_{ordinal:06d}/ "
                "AUTO_COMPRESS = FALSE OVERWRITE = FALSE"
            )
            uploaded = _result_rows(cursor)
            if len(uploaded) != 1 or uploaded[0].get("status") != "UPLOADED":
                raise WarehouseLoadError(f"Parquet upload was not confirmed for file {ordinal}")

        cursor.execute(_copy_statement(landing, stage))
        copied = _result_rows(cursor)
        if (
            len(copied) != len(plan.parquet_files)
            or any(row.get("status") != "LOADED" for row in copied)
            or sum(int(row.get("rows_loaded", 0)) for row in copied) != expected_rows
        ):
            raise WarehouseLoadError("COPY results do not match the spatial audit")

        cursor.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT device_id), COALESCE(COUNT_IF("
            f"event_ts IS NULL OR NOT ({window}) "
            "OR device_id IS NULL OR TRIM(device_id) = '' "
            "OR store_id IS NULL OR TRIM(store_id) = '' "
            "OR store_status IS NULL OR store_status NOT IN ('existing', 'proposed', 'candidate')"
            f"), 0) FROM {landing}",
            (start, end),
        )
        summary = cursor.fetchone()
        if summary is None or tuple(summary) != (expected_rows, expected_devices, 0):
            raise WarehouseLoadError("Loaded counts, device IDs, or retail-day bounds are invalid")
        cursor.execute(
            f"SELECT COUNT(*) FROM (SELECT device_id, event_ts, store_id FROM {landing} "
            "GROUP BY device_id, event_ts, store_id HAVING COUNT(*) > 1)"
        )
        duplicates = cursor.fetchone()
        if duplicates is None or duplicates[0] != 0:
            raise WarehouseLoadError("Loaded matches contain duplicate ping/store keys")

        cursor.execute("BEGIN TRANSACTION")
        try:
            cursor.execute(f"DELETE FROM {config.target_table} WHERE {window}", (start, end))
            columns = ", ".join(MATCH_COLUMNS)
            cursor.execute(
                f"INSERT INTO {config.target_table} ({columns}) SELECT {columns} FROM {landing}"
            )
            cursor.execute(
                f"SELECT COUNT(*) FROM {config.target_table} WHERE {window}", (start, end)
            )
            target_count = cursor.fetchone()
            if target_count is None or target_count[0] != expected_rows:
                raise WarehouseLoadError("Target batch count does not match the spatial audit")
            cursor.execute("COMMIT")
        except BaseException:
            # Closing the session is an additional rollback safeguard if the network fails here.
            try:
                cursor.execute("ROLLBACK")
            except Exception:
                pass
            raise

    return {
        "status": "published",
        "run_date_local": config.run_date.isoformat(),
        "target_table": config.target_table,
        "loaded_rows": expected_rows,
        "unique_devices": expected_devices,
        "uploaded_files": len(plan.parquet_files),
    }


def read_connection_settings(environment: Mapping[str, str]) -> dict[str, Any]:
    """Read worker credentials without including them in the load plan or CLI arguments."""

    settings: dict[str, Any] = {}
    for name in ("ACCOUNT", "USER", "WAREHOUSE"):
        value = environment.get(f"DBT_SNOWFLAKE_{name}", "").strip()
        if not value or value == "replace-me":
            raise WarehouseLoadError(f"DBT_SNOWFLAKE_{name} must be configured")
        settings[name.lower()] = value
    key_path = environment.get("GEOPULSE_SNOWFLAKE_PRIVATE_KEY_FILE", "").strip()
    if key_path:
        settings["authenticator"] = "SNOWFLAKE_JWT"
        settings["private_key_file"] = key_path
        passphrase = environment.get("GEOPULSE_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        if passphrase:
            settings["private_key_file_pwd"] = passphrase
    else:
        password = environment.get("DBT_SNOWFLAKE_PASSWORD", "")
        if not password or password == "replace-me":
            raise WarehouseLoadError("Configure a Snowflake password or private key file")
        settings["password"] = password
    settings.update(
        database=_identifier(environment.get("DBT_SNOWFLAKE_DATABASE", "GEOPULSE")),
        schema=_identifier(environment.get("DBT_SNOWFLAKE_SOURCE_SCHEMA", "SPATIAL")),
        role=environment.get("DBT_SNOWFLAKE_ROLE", "GEOPULSE_TRANSFORMER"),
        autocommit=True,
        session_parameters={"TIMEZONE": "UTC", "QUERY_TAG": "geopulse_spatial_publisher"},
    )
    return settings


def connect_snowflake(settings: Mapping[str, Any]) -> Any:
    try:
        import snowflake.connector
    except ModuleNotFoundError as exc:
        raise WarehouseLoadError("Install the GeoPulse warehouse extra: .[warehouse]") from exc
    return snowflake.connector.connect(**settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish a validated retail-day spatial batch.")
    parser.add_argument("--run-date", required=True, type=date.fromisoformat)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--matches", required=True, type=Path)
    parser.add_argument("--expected-ping-rows", required=True, type=int)
    parser.add_argument("--max-ping-rejection-rate", type=float, default=0.01)
    parser.add_argument("--max-rejected-store-rows", type=int, default=0)
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate and print a local load plan"
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    connection = None
    try:
        try:
            policy = SpatialQualityPolicy(
                args.expected_ping_rows,
                args.max_ping_rejection_rate,
                args.max_rejected_store_rows,
            )
        except ValueError as exc:
            raise WarehouseLoadError(str(exc)) from exc
        config = BatchLoadConfig(
            run_date=args.run_date,
            matches_path=args.matches,
            audit_path=args.audit,
            policy=policy,
            database=os.environ.get("DBT_SNOWFLAKE_DATABASE", "GEOPULSE"),
            schema=os.environ.get("DBT_SNOWFLAKE_SOURCE_SCHEMA", "SPATIAL"),
        )
        plan = plan_spatial_load(config)
        if args.dry_run:
            result = plan.as_dict()
        else:
            settings = read_connection_settings(os.environ)
            connection = connect_snowflake(settings)
            result = publish_spatial_batch(connection, plan)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (WarehouseLoadError, SpatialQualityError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        # Connector messages can contain authentication details. Log only the error class.
        print(f"Snowflake publication failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
