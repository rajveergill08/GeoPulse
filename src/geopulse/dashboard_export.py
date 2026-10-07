"""Export one validated, aggregate-only Snowflake snapshot for the React dashboard."""

from __future__ import annotations

import argparse
import csv
import errno
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from itertools import chain
from pathlib import Path
from typing import Any

from geopulse.orchestration import PIPELINE_TIMEZONE
from geopulse.warehouse import (
    WarehouseLoadError,
    connect_snowflake,
    read_connection_settings,
)

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
STORE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
STORE_COLUMNS = (
    "store_id",
    "store_name",
    "status",
    "latitude",
    "longitude",
    "catchment_radius_m",
)
MART_COLUMNS = (
    "existing_store_id",
    "candidate_store_id",
    "candidate_store_status",
    "traffic_date_local",
    "retail_timezone",
    "daypart",
    "existing_store_unique_visitors",
    "candidate_store_unique_visitors",
    "shared_visitors",
    "ordered_candidate_to_existing_visitors",
    "incremental_candidate_visitors",
    "cannibalization_rate",
    "candidate_overlap_rate",
    "candidate_incremental_reach_rate",
)
HOURLY_COLUMNS = (
    "store_id",
    "traffic_date_local",
    "event_hour_local",
    "retail_timezone",
    "unique_visitors",
    "ping_count",
)
DAYPARTS = frozenset({"morning_commute", "midday", "evening_commute", "off_peak"})
RATE_TOLERANCE = Decimal("0.000001")  # dbt rounds rates to six decimal places.
MAX_SAFE_JS_INTEGER = 2**53 - 1
PUBLICATION_LOCK_TIMEOUT_SECONDS = 30


class DashboardExportError(ValueError):
    """The dashboard snapshot could not be created without losing integrity."""


def _identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise DashboardExportError("Snowflake database and schema need simple unquoted identifiers")
    return value.upper()


def _run_date(value: str) -> date:
    if not DATE_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("Use an ISO calendar date: YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use a valid ISO calendar date: YYYY-MM-DD") from exc


@dataclass(frozen=True)
class DashboardExportConfig:
    run_date: date
    stores_path: Path
    output_path: Path
    database: str = "GEOPULSE"
    dbt_schema: str = "ANALYTICS"
    retail_timezone: str = PIPELINE_TIMEZONE
    synthetic: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.run_date, date) or isinstance(self.run_date, datetime):
            raise DashboardExportError("run_date must be a calendar date")
        database = _identifier(self.database)
        dbt_schema = _identifier(self.dbt_schema)
        # dbt's default generate_schema_name appends the model's +schema to target.schema.
        _identifier(dbt_schema + "_MARTS")
        object.__setattr__(self, "database", database)
        object.__setattr__(self, "dbt_schema", dbt_schema)
        object.__setattr__(self, "stores_path", Path(self.stores_path).expanduser().resolve())
        object.__setattr__(self, "output_path", Path(self.output_path).expanduser().resolve())
        if self.stores_path == self.output_path:
            raise DashboardExportError("The dashboard output cannot replace the store reference")
        # The current synthetic generator and dbt defaults are fixed to Asia/Kolkata.
        # Avoid depending on a host's optional IANA tzdata installation for this check.
        if self.retail_timezone != PIPELINE_TIMEZONE:
            raise DashboardExportError("The retail timezone must be Asia/Kolkata")
        if not isinstance(self.synthetic, bool):
            raise DashboardExportError("synthetic must be a boolean")

    @property
    def mart_schema(self) -> str:
        return self.dbt_schema + "_MARTS"

    @property
    def mart_table(self) -> str:
        return f"{self.database}.{self.mart_schema}.FCT_STORE_CANNIBALIZATION"

    @property
    def hourly_mart_table(self) -> str:
        return f"{self.database}.{self.mart_schema}.FCT_STORE_HOURLY_FOOTFALL"


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise DashboardExportError(f"Invalid {field} in dashboard source")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DashboardExportError(f"Invalid {field} in dashboard source") from exc
    if not number.is_finite():
        raise DashboardExportError(f"Invalid {field} in dashboard source")
    return number


def _positive_float(
    value: object, field: str, *, lower: int | None = None, upper: int | None = None
) -> float:
    number = _decimal(value, field)
    if (lower is not None and number < lower) or (upper is not None and number > upper):
        raise DashboardExportError(f"Invalid {field} in store reference")
    result = float(number)
    if not (-float("inf") < result < float("inf")):
        raise DashboardExportError(f"Invalid {field} in store reference")
    return result


def read_stores(path: Path) -> list[dict[str, Any]]:
    """Read and validate the public, non-device-level store reference."""

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or tuple(reader.fieldnames) != STORE_COLUMNS:
                raise DashboardExportError("Store reference has an unexpected CSV header")
            stores: list[dict[str, Any]] = []
            ids: set[str] = set()
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise DashboardExportError("Store reference has a malformed row")
                store_id = row["store_id"].strip()
                store_name = row["store_name"].strip()
                status = row["status"].strip()
                if (
                    not STORE_ID_PATTERN.fullmatch(store_id)
                    or store_id in ids
                    or not store_name
                    or status not in {"existing", "proposed", "candidate"}
                ):
                    raise DashboardExportError(
                        "Store reference contains invalid or duplicate stores"
                    )
                latitude = _positive_float(row["latitude"], "latitude", lower=-90, upper=90)
                longitude = _positive_float(row["longitude"], "longitude", lower=-180, upper=180)
                radius = _positive_float(row["catchment_radius_m"], "catchment radius")
                if radius <= 0:
                    raise DashboardExportError("Store catchment radius must be positive")
                stores.append(
                    {
                        "storeId": store_id,
                        "storeName": store_name,
                        "status": status,
                        "latitude": latitude,
                        "longitude": longitude,
                        "catchmentRadiusM": radius,
                    }
                )
                ids.add(store_id)
    except OSError as exc:
        raise DashboardExportError("Could not read the store reference CSV") from exc
    if not stores:
        raise DashboardExportError("Store reference CSV is empty")
    return stores


def read_dashboard_connection_settings(
    environment: Mapping[str, str], config: DashboardExportConfig
) -> dict[str, Any]:
    """Reuse warehouse authentication, but point the session to dbt's mart schema."""

    # The warehouse loader's SOURCE_SCHEMA option is unrelated to this mart.
    settings = read_connection_settings({**environment, "DBT_SNOWFLAKE_SOURCE_SCHEMA": "SPATIAL"})
    settings["database"] = config.database
    settings["schema"] = config.mart_schema
    dashboard_role = environment.get("GEOPULSE_DASHBOARD_SNOWFLAKE_ROLE", "").strip()
    if dashboard_role:
        settings["role"] = _identifier(dashboard_role)
    settings["session_parameters"] = {
        "TIMEZONE": "UTC",
        "QUERY_TAG": "geopulse_dashboard_export",
    }
    return settings


def fetch_aggregate_rows(connection: Any, config: DashboardExportConfig) -> list[dict[str, Any]]:
    """Select only aggregate fact columns, never raw device identifiers."""

    sql = (
        f"SELECT {', '.join(MART_COLUMNS)} FROM {config.mart_table} "
        "WHERE TRAFFIC_DATE_LOCAL = TO_DATE(%s) "
        "ORDER BY EXISTING_STORE_ID, CANDIDATE_STORE_ID, TRAFFIC_DATE_LOCAL, DAYPART"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, (config.run_date.isoformat(),))
        names = tuple(column[0].lower() for column in cursor.description)
        if names != MART_COLUMNS:
            raise DashboardExportError("Snowflake mart returned unexpected aggregate columns")
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def fetch_hourly_rows(connection: Any, config: DashboardExportConfig) -> list[dict[str, Any]]:
    """Select only store/hour counts for the requested retail-local day."""

    sql = (
        f"SELECT {', '.join(HOURLY_COLUMNS)} FROM {config.hourly_mart_table} "
        "WHERE TRAFFIC_DATE_LOCAL = TO_DATE(%s) "
        "ORDER BY STORE_ID, TRAFFIC_DATE_LOCAL, EVENT_HOUR_LOCAL"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, (config.run_date.isoformat(),))
        names = tuple(column[0].lower() for column in cursor.description)
        if names != HOURLY_COLUMNS:
            raise DashboardExportError(
                "Snowflake hourly mart returned unexpected aggregate columns"
            )
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _count(value: object, field: str, *, positive: bool = False) -> int:
    number = _decimal(value, field)
    if (
        number != number.to_integral_value()
        or number < (1 if positive else 0)
        or number > MAX_SAFE_JS_INTEGER
    ):
        raise DashboardExportError(f"Invalid {field} in dashboard mart")
    return int(number)


def _rate(value: object, field: str) -> Decimal:
    number = _decimal(value, field)
    if number < 0 or number > 1:
        raise DashboardExportError(f"Invalid {field} in dashboard mart")
    return number


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        raise DashboardExportError("The mart returned a timestamp instead of a local date")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and DATE_PATTERN.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise DashboardExportError("The mart returned an invalid local date")


def _build_hourly_footfall(
    config: DashboardExportConfig,
    store_index: Mapping[str, dict[str, Any]],
    rows: Sequence[dict[str, Any]],
    flow_store_ids: set[str],
) -> list[dict[str, Any]]:
    if not rows:
        raise DashboardExportError("No hourly footfall exists for the requested retail day")
    hourly_footfall: list[dict[str, Any]] = []
    grains: set[tuple[str, int]] = set()
    covered_stores: set[str] = set()
    for row in rows:
        store_id = row["store_id"]
        traffic_date = _as_date(row["traffic_date_local"])
        hour = row["event_hour_local"]
        if not isinstance(store_id, str) or store_id not in store_index:
            raise DashboardExportError("The hourly mart references an unknown store")
        if traffic_date != config.run_date:
            raise DashboardExportError("The hourly mart returned a different retail date")
        if row["retail_timezone"] != config.retail_timezone:
            raise DashboardExportError(
                "The hourly mart retail timezone differs from the configured one"
            )
        if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
            raise DashboardExportError("The hourly mart returned an invalid local hour")
        grain = (store_id, hour)
        if grain in grains:
            raise DashboardExportError("The hourly mart contains duplicate store/hour rows")
        grains.add(grain)
        unique_visitors = _count(row["unique_visitors"], "hourly unique visitors")
        ping_count = _count(row["ping_count"], "hourly ping count")
        if unique_visitors > ping_count:
            raise DashboardExportError("The hourly mart visitor count exceeds the ping count")
        covered_stores.add(store_id)
        hourly_footfall.append(
            {
                "storeId": store_id,
                "trafficDateLocal": traffic_date.isoformat(),
                "hourLocal": hour,
                "uniqueVisitors": unique_visitors,
                "pingCount": ping_count,
            }
        )
    missing = flow_store_ids - covered_stores
    if missing:
        raise DashboardExportError("Hourly footfall is missing for a flow-referenced store")
    return sorted(
        hourly_footfall,
        key=lambda row: (row["trafficDateLocal"], row["storeId"], row["hourLocal"]),
    )


def build_snapshot(
    config: DashboardExportConfig,
    stores: Sequence[dict[str, Any]],
    rows: Sequence[dict[str, Any]],
    *,
    hourly_rows: Sequence[dict[str, Any]] | None = None,
    exported_at: datetime | None = None,
) -> dict[str, Any]:
    """Map Snowflake decimals/dates to the exact React JSON contract."""

    if not rows:
        raise DashboardExportError("No aggregate flows exist for the requested retail day")
    store_index = {store["storeId"]: store for store in stores}
    if len(store_index) != len(stores):
        raise DashboardExportError("Store IDs must be unique")
    flows: list[dict[str, Any]] = []
    grains: set[tuple[str, str, str, str]] = set()
    for row in rows:
        existing_id = row["existing_store_id"]
        candidate_id = row["candidate_store_id"]
        status = row["candidate_store_status"]
        daypart = row["daypart"]
        traffic_date = _as_date(row["traffic_date_local"])
        if traffic_date != config.run_date:
            raise DashboardExportError("The mart returned a different retail date")
        if row["retail_timezone"] != config.retail_timezone:
            raise DashboardExportError("The mart retail timezone differs from the configured one")
        if (
            not isinstance(existing_id, str)
            or not isinstance(candidate_id, str)
            or existing_id not in store_index
            or candidate_id not in store_index
            or existing_id == candidate_id
        ):
            raise DashboardExportError("A mart flow references an invalid store pair")
        if (
            store_index[existing_id]["status"] != "existing"
            or store_index[candidate_id]["status"] not in {"proposed", "candidate"}
            or status != store_index[candidate_id]["status"]
        ):
            raise DashboardExportError("Mart and store reference statuses do not agree")
        if daypart not in DAYPARTS:
            raise DashboardExportError("The mart returned an invalid daypart")
        grain = (existing_id, candidate_id, traffic_date.isoformat(), daypart)
        if grain in grains:
            raise DashboardExportError("The mart contains duplicate store/daypart flows")
        grains.add(grain)

        existing = _count(row["existing_store_unique_visitors"], "existing visitors", positive=True)
        candidate = _count(
            row["candidate_store_unique_visitors"], "candidate visitors", positive=True
        )
        shared = _count(row["shared_visitors"], "shared visitors")
        ordered = _count(row.get("ordered_candidate_to_existing_visitors"), "ordered visitors")
        incremental = _count(row["incremental_candidate_visitors"], "incremental visitors")
        if (
            shared > min(existing, candidate)
            or ordered > shared
            or incremental != candidate - shared
        ):
            raise DashboardExportError("Mart visitor counts are inconsistent")
        cannibalization = _rate(row["cannibalization_rate"], "cannibalization rate")
        overlap = _rate(row["candidate_overlap_rate"], "candidate overlap rate")
        reach = _rate(row["candidate_incremental_reach_rate"], "incremental reach rate")
        if any(
            difference > RATE_TOLERANCE
            for difference in (
                abs(cannibalization - Decimal(shared) / Decimal(existing)),
                abs(overlap - Decimal(shared) / Decimal(candidate)),
                abs(reach - Decimal(incremental) / Decimal(candidate)),
                abs(overlap + reach - 1),
            )
        ):
            raise DashboardExportError("Mart visitor rates are inconsistent with counts")
        flows.append(
            {
                "scenarioId": "|".join(grain),
                "existingStoreId": existing_id,
                "candidateStoreId": candidate_id,
                "trafficDateLocal": traffic_date.isoformat(),
                "daypart": daypart,
                "existingStoreUniqueVisitors": existing,
                "candidateStoreUniqueVisitors": candidate,
                "sharedVisitors": shared,
                "orderedCandidateToExistingVisitors": ordered,
                "incrementalCandidateVisitors": incremental,
                "cannibalizationRate": float(cannibalization),
                "candidateOverlapRate": float(overlap),
                "candidateIncrementalReachRate": float(reach),
            }
        )
    flow_store_ids = {
        store_id
        for flow in flows
        for store_id in (flow["existingStoreId"], flow["candidateStoreId"])
    }
    hourly_footfall = (
        []
        if hourly_rows is None
        else _build_hourly_footfall(config, store_index, hourly_rows, flow_store_ids)
    )
    moment = exported_at or datetime.now(UTC)
    if moment.tzinfo is None:
        raise DashboardExportError("Snapshot generation time must include a timezone")
    refreshed_at = moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "metadata": {
            "source": (
                f"Snowflake {config.mart_table} + store reference CSV"
                if hourly_rows is None
                else f"Snowflake {config.mart_table} + {config.hourly_mart_table}"
                " + store reference CSV"
            ),
            "refreshedAt": refreshed_at,
            "timezone": "UTC",
            "retailTimezone": config.retail_timezone,
            "synthetic": config.synthetic,
        },
        "stores": sorted(stores, key=lambda store: store["storeId"]),
        "flows": sorted(
            flows,
            key=lambda flow: (
                flow["trafficDateLocal"],
                flow["existingStoreId"],
                flow["candidateStoreId"],
                flow["daypart"],
            ),
        ),
        "hourlyFootfall": hourly_footfall,
    }


def write_snapshot_atomically(output_path: Path, snapshot: Mapping[str, Any]) -> None:
    """Replace a previous dashboard JSON only after a complete UTF-8 temp write."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(snapshot, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _snapshot_retail_date(snapshot: object, retail_timezone: str) -> date:
    """Return the one data date represented by an aggregate dashboard snapshot."""

    if not isinstance(snapshot, Mapping):
        raise DashboardExportError("Dashboard snapshot has no unambiguous retail date")
    metadata = snapshot.get("metadata")
    flows = snapshot.get("flows")
    hourly = snapshot.get("hourlyFootfall")
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("retailTimezone") != retail_timezone
        or not isinstance(flows, list)
        or not flows
        or not isinstance(hourly, list)
    ):
        raise DashboardExportError("Dashboard snapshot has no unambiguous retail date")

    traffic_dates: set[date] = set()
    for row in chain(flows, hourly):
        if not isinstance(row, Mapping):
            raise DashboardExportError("Dashboard snapshot has no unambiguous retail date")
        value = row.get("trafficDateLocal")
        if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
            raise DashboardExportError("Dashboard snapshot has no unambiguous retail date")
        try:
            traffic_dates.add(date.fromisoformat(value))
        except ValueError as exc:
            raise DashboardExportError("Dashboard snapshot has no unambiguous retail date") from exc
    if len(traffic_dates) != 1:
        raise DashboardExportError("Dashboard snapshot has no unambiguous retail date")
    return next(iter(traffic_dates))


@contextmanager
def _publication_lock(output_path: Path) -> Iterator[None]:
    """Serialize independent publishers of the same output on Windows and POSIX."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the sibling lock file: removing it while another process waits can split the lock.
    lock_path = output_path.with_name(f".{output_path.name}.lock")
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()

            def acquire() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

        else:
            import fcntl

            def acquire() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        deadline = time.monotonic() + PUBLICATION_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                    raise
                if time.monotonic() >= deadline:
                    raise DashboardExportError(
                        "Timed out waiting for the dashboard publication lock"
                    ) from exc
                time.sleep(0.1)
        try:
            yield
        finally:
            release()


def publish_latest_snapshot(config: DashboardExportConfig, snapshot: Mapping[str, Any]) -> None:
    """Publish only if the requested retail day does not roll this output backward."""

    incoming_date = _snapshot_retail_date(snapshot, config.retail_timezone)
    if incoming_date != config.run_date:
        raise DashboardExportError("Dashboard snapshot date differs from the requested run date")

    with _publication_lock(config.output_path):
        if config.output_path.exists() or config.output_path.is_symlink():
            try:
                existing = json.loads(config.output_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DashboardExportError(
                    "Existing dashboard snapshot is unreadable; refusing to replace it"
                ) from exc
            existing_date = _snapshot_retail_date(existing, config.retail_timezone)
            if incoming_date < existing_date:
                raise DashboardExportError(
                    "An older retail day cannot replace this dashboard snapshot; "
                    "use a date-specific output path for backfills"
                )
        write_snapshot_atomically(config.output_path, snapshot)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a validated Snowflake dashboard snapshot.")
    parser.add_argument("--run-date", required=True, type=_run_date)
    parser.add_argument("--stores", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--synthetic", action="store_true", help="Declare that the source mart uses synthetic data"
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    connection = None
    try:
        config = DashboardExportConfig(
            run_date=args.run_date,
            stores_path=args.stores,
            output_path=args.output,
            database=os.environ.get("DBT_SNOWFLAKE_DATABASE", "GEOPULSE"),
            dbt_schema=os.environ.get("DBT_SNOWFLAKE_SCHEMA", "ANALYTICS"),
            retail_timezone=os.environ.get("GEOPULSE_RETAIL_TIMEZONE", PIPELINE_TIMEZONE),
            synthetic=args.synthetic,
        )
        if not config.synthetic:
            raise DashboardExportError(
                "Dashboard export is synthetic-only until real mobility aggregates have an "
                "approved privacy and small-cell suppression policy"
            )
        stores = read_stores(config.stores_path)
        settings = read_dashboard_connection_settings(os.environ, config)
        connection = connect_snowflake(settings)
        rows = fetch_aggregate_rows(connection, config)
        hourly_rows = fetch_hourly_rows(connection, config)
        snapshot = build_snapshot(config, stores, rows, hourly_rows=hourly_rows)
        publish_latest_snapshot(config, snapshot)
        print(
            json.dumps(
                {
                    "status": "exported",
                    "run_date_local": config.run_date.isoformat(),
                    "target": str(config.output_path),
                    "flow_count": len(snapshot["flows"]),
                    "hourly_footfall_count": len(snapshot["hourlyFootfall"]),
                    "synthetic": config.synthetic,
                },
                sort_keys=True,
            )
        )
        return 0
    except (DashboardExportError, WarehouseLoadError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        # Connector and filesystem exceptions may contain authentication details.
        print(f"Dashboard export failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
