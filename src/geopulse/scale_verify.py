"""Opt-in, synthetic-only generator-to-Sedona spatial verification.

This command records a reproducible local smoke or scale run. It does not
connect to Snowflake, run dbt/Airflow, or measure Spark's peak memory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from geopulse.quality import SpatialQualityPolicy, validate_spatial_output
from geopulse.spatial import DEFAULT_MAVEN_PACKAGES
from geopulse.synthetic import BENGALURU, GeneratorConfig

STORE_FIELDS = (
    "store_id",
    "store_name",
    "status",
    "latitude",
    "longitude",
    "catchment_radius_m",
)


class ScaleVerificationError(RuntimeError):
    """Raised when a verification stage fails or its output cannot be trusted."""


@dataclass(frozen=True)
class ScaleVerificationConfig:
    run_date: date
    stores_path: Path
    output_path: Path
    devices: int = 100
    interval_minutes: int = 15
    seed: int = 42
    master: str = "local[2]"
    shuffle_partitions: int = 8
    maven_packages: str = DEFAULT_MAVEN_PACKAGES
    synthetic_stores: int | None = None
    max_ping_rejection_rate: float = 0.0
    max_rejected_store_rows: int = 0

    def __post_init__(self) -> None:
        GeneratorConfig(
            devices=self.devices,
            days=1,
            interval_minutes=self.interval_minutes,
            start_date=self.run_date,
            seed=self.seed,
        )
        SpatialQualityPolicy(
            expected_ping_rows=self.expected_ping_rows,
            max_ping_rejection_rate=self.max_ping_rejection_rate,
            max_rejected_store_rows=self.max_rejected_store_rows,
        )
        if self.shuffle_partitions <= 0:
            raise ValueError("shuffle_partitions must be greater than zero")
        if self.synthetic_stores is not None and not 1 <= self.synthetic_stores <= 100_000:
            raise ValueError("synthetic_stores must be between 1 and 100000")
        if not self.master.strip() or not self.maven_packages.strip():
            raise ValueError("master and maven_packages must not be empty")

    @property
    def expected_ping_rows(self) -> int:
        return self.devices * (1_440 // self.interval_minutes)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        candidate = candidate.parent
    return candidate


def _machine_context(output_path: Path, config: ScaleVerificationConfig) -> dict[str, Any]:
    context: dict[str, Any] = {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "logical_cpu_count": os.cpu_count(),
        "disk_free_bytes_at_start": shutil.disk_usage(
            _nearest_existing_directory(output_path.parent)
        ).free,
        "spark_master": config.master,
        "shuffle_partitions": config.shuffle_partitions,
        "spark_peak_memory_measured": False,
    }
    if hasattr(os, "sysconf"):
        try:
            context["physical_memory_bytes"] = os.sysconf("SC_PHYS_PAGES") * os.sysconf(
                "SC_PAGE_SIZE"
            )
        except (OSError, ValueError, AttributeError):
            pass
    return context


def _read_reference_stores(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != STORE_FIELDS:
            raise ScaleVerificationError("Store reference CSV does not match the spatial schema")
        return list(reader)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_stores(output: Path, reference: list[dict[str, str]], requested_count: int) -> Path:
    """Preserve the reference locations and add a deterministic Bengaluru grid."""

    if requested_count < len(reference):
        raise ScaleVerificationError(
            f"synthetic_stores={requested_count} is below {len(reference)} reference stores"
        )
    destination = output / "benchmark_stores.csv"
    generated_count = requested_count - len(reference)
    columns = max(1, math.ceil(math.sqrt(generated_count)))
    rows = max(1, math.ceil(generated_count / columns))
    existing_ids = {row["store_id"] for row in reference}

    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=STORE_FIELDS)
        writer.writeheader()
        writer.writerows(reference)
        for index in range(generated_count):
            identifier = f"benchmark_store_{index + 1:06d}"
            if identifier in existing_ids:
                raise ScaleVerificationError(
                    f"Generated store ID conflicts with reference: {identifier}"
                )
            grid_row, grid_column = divmod(index, columns)
            latitude = (
                BENGALURU.min_latitude
                + (grid_row + 0.5) * (BENGALURU.max_latitude - BENGALURU.min_latitude) / rows
            )
            longitude = (
                BENGALURU.min_longitude
                + (grid_column + 0.5)
                * (BENGALURU.max_longitude - BENGALURU.min_longitude)
                / columns
            )
            writer.writerow(
                {
                    "store_id": identifier,
                    "store_name": f"Synthetic Benchmark Store {index + 1}",
                    "status": "candidate",
                    "latitude": f"{latitude:.6f}",
                    "longitude": f"{longitude:.6f}",
                    "catchment_radius_m": "500",
                }
            )
    return destination


def _commands(
    config: ScaleVerificationConfig, output: Path, stores_path: Path
) -> list[tuple[str, list[str]]]:
    pings = output / "mobile_pings.csv.gz"
    spatial = output / "spatial"
    return [
        (
            "generate",
            [
                sys.executable,
                "-m",
                "geopulse.synthetic",
                "--devices",
                str(config.devices),
                "--days",
                "1",
                "--interval-minutes",
                str(config.interval_minutes),
                "--start-date",
                config.run_date.isoformat(),
                "--seed",
                str(config.seed),
                "--output",
                str(pings),
            ],
        ),
        (
            "spatial_join",
            [
                sys.executable,
                "-m",
                "geopulse.spatial",
                "--pings",
                str(pings),
                "--stores",
                str(stores_path),
                "--output",
                str(spatial),
                "--master",
                config.master,
                "--shuffle-partitions",
                str(config.shuffle_partitions),
                "--maven-packages",
                config.maven_packages,
                "--write-mode",
                "overwrite",
            ],
        ),
        (
            "quality_gate",
            [
                sys.executable,
                "-m",
                "geopulse.quality",
                "--audit",
                str(spatial / "audit"),
                "--matches",
                str(spatial / "matches"),
                "--expected-ping-rows",
                str(config.expected_ping_rows),
                "--max-ping-rejection-rate",
                str(config.max_ping_rejection_rate),
                "--max-rejected-store-rows",
                str(config.max_rejected_store_rows),
            ],
        ),
    ]


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def run_verification(config: ScaleVerificationConfig) -> dict[str, Any]:
    """Run all three stages in a new output directory and retain honest evidence."""

    output = config.output_path.expanduser().resolve()
    stores = config.stores_path.expanduser().resolve()
    if not stores.is_file():
        raise ScaleVerificationError(f"Store reference file is unavailable: {stores}")
    if output.exists():
        raise ScaleVerificationError(f"Output already exists; choose a new path: {output}")
    reference_stores = _read_reference_stores(stores)
    if config.synthetic_stores is not None and config.synthetic_stores < len(reference_stores):
        raise ScaleVerificationError(
            f"synthetic_stores={config.synthetic_stores} is below "
            f"{len(reference_stores)} reference stores"
        )
    reference_sha256 = _sha256_file(stores)

    output.mkdir(parents=True, exist_ok=False)
    evidence_path = output / "verification.json"
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "synthetic_only": True,
        "run_date": config.run_date.isoformat(),
        "devices": config.devices,
        "interval_minutes": config.interval_minutes,
        "expected_ping_rows": config.expected_ping_rows,
        "seed": config.seed,
        "stores_path": str(stores),
        "reference_store_rows": len(reference_stores),
        "reference_stores_sha256": reference_sha256,
        "synthetic_stores": config.synthetic_stores,
        "expected_store_rows": config.synthetic_stores or len(reference_stores),
        "output_path": str(output),
        "started_at_utc": _utc_now(),
        "machine": {"spark_peak_memory_measured": False},
        "limitations": [
            "No Snowflake, dbt, Airflow, or dashboard execution is included.",
            "Spark/JVM peak memory is not measured by this harness.",
            "A small smoke run does not prove ten-million-point scalability.",
        ],
        "stages": [],
    }
    _write_evidence(evidence_path, evidence)

    current_stage = "machine_context"
    try:
        evidence["machine"] = _machine_context(output, config)
        _write_evidence(evidence_path, evidence)
        spatial_stores = stores
        if config.synthetic_stores is not None:
            current_stage = "prepare_stores"
            started = time.perf_counter()
            spatial_stores = _prepare_stores(output, reference_stores, config.synthetic_stores)
            evidence["spatial_stores_sha256"] = _sha256_file(spatial_stores)
            evidence["stages"].append(
                {
                    "name": current_stage,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "output_path": str(spatial_stores),
                    "store_rows": config.synthetic_stores,
                }
            )
            _write_evidence(evidence_path, evidence)
        for stage_name, command in _commands(config, output, spatial_stores):
            current_stage = stage_name
            log_path = output / f"{stage_name}.log"
            started = time.perf_counter()
            print(f"Starting {stage_name}; log: {log_path}", flush=True)
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    command, stdout=log, stderr=subprocess.STDOUT, check=False
                )
            elapsed = round(time.perf_counter() - started, 3)
            evidence["stages"].append(
                {
                    "name": stage_name,
                    "elapsed_seconds": elapsed,
                    "return_code": completed.returncode,
                    "log_path": str(log_path),
                }
            )
            _write_evidence(evidence_path, evidence)
            if completed.returncode != 0:
                raise ScaleVerificationError(
                    f"{stage_name} exited with code {completed.returncode}; inspect {log_path}"
                )
            print(f"Completed {stage_name} in {elapsed:.3f}s", flush=True)

        current_stage = "audit_recheck"
        report = validate_spatial_output(
            output / "spatial" / "audit",
            output / "spatial" / "matches",
            SpatialQualityPolicy(
                expected_ping_rows=config.expected_ping_rows,
                max_ping_rejection_rate=config.max_ping_rejection_rate,
                max_rejected_store_rows=config.max_rejected_store_rows,
            ),
        )
        evidence["quality_report"] = report.as_dict()
        expected_store_rows = evidence["expected_store_rows"]
        if (
            report.metrics["raw_store_rows"] != expected_store_rows
            or report.metrics["valid_store_rows"] != expected_store_rows
        ):
            raise ScaleVerificationError(
                "Spatial audit does not contain the expected number of valid store polygons: "
                f"expected {expected_store_rows}, raw {report.metrics['raw_store_rows']}, "
                f"valid {report.metrics['valid_store_rows']}"
            )
        evidence["status"] = "passed"
        evidence["finished_at_utc"] = _utc_now()
        _write_evidence(evidence_path, evidence)
        return evidence
    except KeyboardInterrupt:
        evidence["status"] = "interrupted"
        evidence["failed_stage"] = current_stage
        evidence["finished_at_utc"] = _utc_now()
        _write_evidence(evidence_path, evidence)
        raise
    except Exception as exc:
        evidence["status"] = "failed"
        evidence["failed_stage"] = current_stage
        evidence["failure"] = f"{type(exc).__name__}: {exc}"
        evidence["finished_at_utc"] = _utc_now()
        _write_evidence(evidence_path, evidence)
        raise


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("run date must use YYYY-MM-DD format") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an opt-in synthetic generator, Sedona join, and spatial quality gate."
    )
    parser.add_argument("--run-date", required=True, type=_parse_date)
    parser.add_argument("--stores", required=True, type=Path)
    parser.add_argument(
        "--output", required=True, type=Path, help="New directory; existing paths are refused"
    )
    parser.add_argument("--devices", type=int, default=100)
    parser.add_argument("--interval-minutes", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--master", default="local[2]")
    parser.add_argument("--shuffle-partitions", type=int, default=8)
    parser.add_argument("--maven-packages", default=DEFAULT_MAVEN_PACKAGES)
    parser.add_argument(
        "--synthetic-stores",
        type=int,
        help="Total store rows including --stores reference locations (max 100000)",
    )
    parser.add_argument("--max-ping-rejection-rate", type=float, default=0.0)
    parser.add_argument("--max-rejected-store-rows", type=int, default=0)
    parser.add_argument(
        "--plan", action="store_true", help="Print the plan without creating output"
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = ScaleVerificationConfig(
            run_date=args.run_date,
            stores_path=args.stores,
            output_path=args.output,
            devices=args.devices,
            interval_minutes=args.interval_minutes,
            seed=args.seed,
            master=args.master,
            shuffle_partitions=args.shuffle_partitions,
            maven_packages=args.maven_packages,
            synthetic_stores=args.synthetic_stores,
            max_ping_rejection_rate=args.max_ping_rejection_rate,
            max_rejected_store_rows=args.max_rejected_store_rows,
        )
        output = config.output_path.expanduser().resolve()
        stores = config.stores_path.expanduser().resolve()
        if args.plan:
            if not stores.is_file():
                raise ScaleVerificationError(f"Store reference file is unavailable: {stores}")
            if output.exists():
                raise ScaleVerificationError(f"Output already exists; choose a new path: {output}")
            reference_stores = _read_reference_stores(stores)
            if config.synthetic_stores is not None and config.synthetic_stores < len(
                reference_stores
            ):
                raise ScaleVerificationError(
                    f"synthetic_stores={config.synthetic_stores} is below "
                    f"{len(reference_stores)} reference stores"
                )
            spatial_stores = (
                output / "benchmark_stores.csv" if config.synthetic_stores is not None else stores
            )
            print(
                json.dumps(
                    {
                        "status": "planned_only",
                        "synthetic_only": True,
                        "expected_ping_rows": config.expected_ping_rows,
                        "synthetic_stores": config.synthetic_stores,
                        "expected_store_rows": config.synthetic_stores or len(reference_stores),
                        "reference_stores_sha256": _sha256_file(stores),
                        "output_path": str(output),
                        "spark_peak_memory_measured": False,
                        "commands": [
                            command for _, command in _commands(config, output, spatial_stores)
                        ],
                    },
                    indent=2,
                )
            )
            return 0
        evidence = run_verification(config)
    except (OSError, ValueError, ScaleVerificationError) as exc:
        print(f"Spatial verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": evidence["status"], "evidence": str(output / "verification.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
