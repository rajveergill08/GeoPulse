"""Fail-closed quality checks for Apache Sedona spatial output.

The spatial job writes one JSON audit row per metric and partitioned Parquet
matches. This module validates that output before a daily batch is allowed to
reach Snowflake.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_AUDIT_METRICS = frozenset(
    {
        "raw_ping_rows",
        "valid_ping_rows",
        "rejected_ping_rows",
        "raw_store_rows",
        "valid_store_rows",
        "rejected_store_rows",
        "matched_ping_store_rows",
        "matched_unique_devices",
    }
)


class SpatialQualityError(ValueError):
    """Raised when spatial output is incomplete or violates its contract."""


@dataclass(frozen=True)
class SpatialQualityPolicy:
    """Thresholds that one daily spatial batch must satisfy."""

    expected_ping_rows: int
    max_ping_rejection_rate: float = 0.01
    max_rejected_store_rows: int = 0

    def __post_init__(self) -> None:
        if self.expected_ping_rows <= 0:
            raise ValueError("expected_ping_rows must be greater than zero")
        if not 0.0 <= self.max_ping_rejection_rate <= 1.0:
            raise ValueError("max_ping_rejection_rate must be between 0 and 1")
        if self.max_rejected_store_rows < 0:
            raise ValueError("max_rejected_store_rows must not be negative")


@dataclass(frozen=True)
class SpatialQualityReport:
    """Validated spatial metrics suitable for logging by an orchestrator."""

    metrics: Mapping[str, int]
    ping_rejection_rate: float
    audit_path: str
    matches_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "passed",
            "audit_path": self.audit_path,
            "matches_path": self.matches_path,
            "ping_rejection_rate": self.ping_rejection_rate,
            "metrics": dict(sorted(self.metrics.items())),
        }


def _parse_audit_record(raw_record: object, source: str) -> tuple[str, int]:
    if not isinstance(raw_record, dict):
        raise SpatialQualityError(f"Audit record must be an object: {source}")

    metric = raw_record.get("metric")
    value = raw_record.get("value")
    if not isinstance(metric, str) or not metric.strip():
        raise SpatialQualityError(f"Audit metric name is invalid: {source}")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SpatialQualityError(
            f"Audit metric {metric!r} must be a non-negative integer: {source}"
        )
    return metric.strip(), value


def load_spatial_audit(audit_path: Path | str) -> dict[str, int]:
    """Load Spark JSON part files and require each contract metric exactly once."""

    directory = Path(audit_path).expanduser().resolve()
    if not directory.is_dir():
        raise SpatialQualityError(f"Spatial audit directory is unavailable: {directory}")

    part_files = sorted(directory.glob("part-*.json"))
    if not part_files:
        raise SpatialQualityError(f"Spatial audit has no part JSON files: {directory}")

    metrics: dict[str, int] = {}
    for part_file in part_files:
        try:
            with part_file.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    source = f"{part_file}:{line_number}"
                    try:
                        raw_record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise SpatialQualityError(f"Invalid audit JSON at {source}") from exc
                    metric, value = _parse_audit_record(raw_record, source)
                    if metric in metrics:
                        raise SpatialQualityError(
                            f"Spatial audit metric appears more than once: {metric}"
                        )
                    metrics[metric] = value
        except OSError as exc:
            raise SpatialQualityError(f"Unable to read spatial audit file: {part_file}") from exc

    missing_metrics = sorted(REQUIRED_AUDIT_METRICS.difference(metrics))
    if missing_metrics:
        raise SpatialQualityError(
            "Spatial audit is missing required metrics: " + ", ".join(missing_metrics)
        )
    return metrics


def validate_spatial_metrics(
    metrics: Mapping[str, int],
    policy: SpatialQualityPolicy,
) -> float:
    """Validate row conservation, expected volume, and rejection guardrails."""

    missing_metrics = sorted(REQUIRED_AUDIT_METRICS.difference(metrics))
    if missing_metrics:
        raise SpatialQualityError(
            "Spatial metrics are missing required values: " + ", ".join(missing_metrics)
        )
    for metric in sorted(REQUIRED_AUDIT_METRICS):
        value = metrics[metric]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SpatialQualityError(f"Spatial metric {metric!r} must be a non-negative integer")

    violations: list[str] = []
    raw_pings = metrics["raw_ping_rows"]
    valid_pings = metrics["valid_ping_rows"]
    rejected_pings = metrics["rejected_ping_rows"]
    raw_stores = metrics["raw_store_rows"]
    valid_stores = metrics["valid_store_rows"]
    rejected_stores = metrics["rejected_store_rows"]
    matches = metrics["matched_ping_store_rows"]
    matched_devices = metrics["matched_unique_devices"]

    if raw_pings != policy.expected_ping_rows:
        violations.append(f"raw_ping_rows is {raw_pings}; expected {policy.expected_ping_rows}")
    if raw_pings != valid_pings + rejected_pings:
        violations.append("ping rows do not reconcile: raw must equal valid plus rejected")
    if raw_stores != valid_stores + rejected_stores:
        violations.append("store rows do not reconcile: raw must equal valid plus rejected")
    if valid_stores == 0:
        violations.append("valid_store_rows must be greater than zero")
    if rejected_stores > policy.max_rejected_store_rows:
        violations.append(
            "rejected_store_rows exceeds the configured limit "
            f"({rejected_stores} > {policy.max_rejected_store_rows})"
        )

    ping_rejection_rate = rejected_pings / raw_pings if raw_pings else 1.0
    if ping_rejection_rate > policy.max_ping_rejection_rate:
        violations.append(
            "ping rejection rate exceeds the configured limit "
            f"({ping_rejection_rate:.6f} > {policy.max_ping_rejection_rate:.6f})"
        )
    if matches == 0:
        violations.append("matched_ping_store_rows must be greater than zero")
    if matched_devices == 0:
        violations.append("matched_unique_devices must be greater than zero")
    if matched_devices > valid_pings:
        violations.append("matched_unique_devices cannot exceed valid_ping_rows")
    if matched_devices > matches:
        violations.append("matched_unique_devices cannot exceed matched_ping_store_rows")
    if matches > valid_pings * valid_stores:
        violations.append(
            "matched_ping_store_rows cannot exceed valid_ping_rows multiplied by valid_store_rows"
        )

    if violations:
        raise SpatialQualityError("Spatial quality gate failed: " + "; ".join(violations))
    return ping_rejection_rate


def require_match_parquet(matches_path: Path | str) -> Path:
    """Require plausible Parquet part files under the partitioned match output."""

    directory = Path(matches_path).expanduser().resolve()
    if not directory.is_dir():
        raise SpatialQualityError(f"Spatial matches directory is unavailable: {directory}")

    first_parquet_file: Path | None = None
    for parquet_file in sorted(directory.rglob("*.parquet")):
        if not parquet_file.is_file():
            continue
        if first_parquet_file is None:
            first_parquet_file = parquet_file
        try:
            if parquet_file.stat().st_size < 12:
                raise SpatialQualityError(
                    f"Spatial match Parquet file is truncated: {parquet_file}"
                )
            with parquet_file.open("rb") as handle:
                leading_magic = handle.read(4)
                handle.seek(-4, 2)
                trailing_magic = handle.read(4)
        except OSError as exc:
            raise SpatialQualityError(
                f"Unable to inspect spatial match Parquet file: {parquet_file}"
            ) from exc
        if leading_magic != b"PAR1" or trailing_magic != b"PAR1":
            raise SpatialQualityError(
                f"Spatial match file has invalid Parquet magic bytes: {parquet_file}"
            )

    if first_parquet_file is None:
        raise SpatialQualityError(f"Spatial matches contain no Parquet files: {directory}")
    return first_parquet_file


def validate_spatial_output(
    audit_path: Path | str,
    matches_path: Path | str,
    policy: SpatialQualityPolicy,
) -> SpatialQualityReport:
    """Validate a complete spatial batch before warehouse publication."""

    metrics = load_spatial_audit(audit_path)
    ping_rejection_rate = validate_spatial_metrics(metrics, policy)
    require_match_parquet(matches_path)
    return SpatialQualityReport(
        metrics=metrics,
        ping_rejection_rate=ping_rejection_rate,
        audit_path=str(Path(audit_path).expanduser().resolve()),
        matches_path=str(Path(matches_path).expanduser().resolve()),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Sedona audit metrics and Parquet output before publication."
    )
    parser.add_argument("--audit", required=True, help="Directory containing Spark audit JSON")
    parser.add_argument("--matches", required=True, help="Partitioned Parquet matches directory")
    parser.add_argument("--expected-ping-rows", required=True, type=int)
    parser.add_argument("--max-ping-rejection-rate", type=float, default=0.01)
    parser.add_argument("--max-rejected-store-rows", type=int, default=0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        policy = SpatialQualityPolicy(
            expected_ping_rows=args.expected_ping_rows,
            max_ping_rejection_rate=args.max_ping_rejection_rate,
            max_rejected_store_rows=args.max_rejected_store_rows,
        )
        report = validate_spatial_output(args.audit, args.matches, policy)
    except (SpatialQualityError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
