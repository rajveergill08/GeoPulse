"""Configuration and shell commands for the GeoPulse daily Airflow pipeline.

This module deliberately has no Airflow dependency. Keeping configuration and
command construction lightweight lets the scheduler parse the DAG quickly and
allows the orchestration contract to be unit tested without an Airflow runtime.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PIPELINE_TIMEZONE = "Asia/Kolkata"
PROCESS_DATE_TEMPLATE = "{{ data_interval_start.in_timezone('Asia/Kolkata').format('YYYY-MM-DD') }}"
RUN_PARTITION_TEMPLATE = "{{ data_interval_start.in_timezone('Asia/Kolkata').format('YYYYMMDD') }}"


def _read_positive_integer(
    environment: Mapping[str, str],
    variable_name: str,
    default: int,
) -> int:
    raw_value = environment.get(variable_name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{variable_name} must be greater than zero")
    return value


def _read_integer(
    environment: Mapping[str, str],
    variable_name: str,
    default: int,
) -> int:
    raw_value = environment.get(variable_name, str(default))
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be an integer") from exc


def _read_non_empty(
    environment: Mapping[str, str],
    variable_name: str,
    default: str,
) -> str:
    value = environment.get(variable_name, default).strip()
    if not value:
        raise ValueError(f"{variable_name} must not be empty")
    return value


def _resolve_path(raw_value: str | Path, base_directory: Path) -> Path:
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = base_directory / path
    return path.resolve()


def _templated_path(base_path: Path, *parts: str) -> str:
    """Join paths without allowing Jinja's timezone slash to be normalized."""

    separator = os.sep
    return separator.join((str(base_path).rstrip("/\\"), *parts))


@dataclass(frozen=True)
class DailyPipelineConfig:
    """Runtime settings shared by the tasks in one daily mobility run."""

    project_root: Path
    data_root: Path
    stores_path: Path
    dbt_profiles_dir: Path
    python_executable: str = "python"
    dbt_executable: str = "dbt"
    devices: int = 100_000
    interval_minutes: int = 15
    generator_seed: int = 42
    spark_master: str = "local[*]"
    shuffle_partitions: int = 200
    dbt_target: str = "snowflake"

    def __post_init__(self) -> None:
        if self.devices <= 0:
            raise ValueError("devices must be greater than zero")
        if self.interval_minutes <= 0 or 1_440 % self.interval_minutes != 0:
            raise ValueError("interval_minutes must be a positive divisor of 1440")
        if self.shuffle_partitions <= 0:
            raise ValueError("shuffle_partitions must be greater than zero")
        for field_name in (
            "python_executable",
            "dbt_executable",
            "spark_master",
            "dbt_target",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")

    @classmethod
    def from_environment(
        cls,
        repository_root: Path | str,
        environment: Mapping[str, str] | None = None,
    ) -> DailyPipelineConfig:
        """Build validated configuration from Airflow worker environment variables."""

        values = os.environ if environment is None else environment
        default_root = Path(repository_root).expanduser().resolve()
        project_root = _resolve_path(
            values.get("GEOPULSE_PROJECT_ROOT", default_root),
            default_root,
        )
        data_root = _resolve_path(
            values.get("GEOPULSE_DATA_ROOT", project_root / "data"),
            project_root,
        )
        stores_path = _resolve_path(
            values.get("GEOPULSE_STORES_PATH", data_root / "reference" / "stores.csv"),
            project_root,
        )
        profiles_dir = _resolve_path(
            values.get(
                "GEOPULSE_DBT_PROFILES_DIR",
                project_root / "profiles" / "snowflake",
            ),
            project_root,
        )

        return cls(
            project_root=project_root,
            data_root=data_root,
            stores_path=stores_path,
            dbt_profiles_dir=profiles_dir,
            python_executable=_read_non_empty(
                values,
                "GEOPULSE_PYTHON_BIN",
                "python",
            ),
            dbt_executable=_read_non_empty(values, "GEOPULSE_DBT_BIN", "dbt"),
            devices=_read_positive_integer(values, "GEOPULSE_DEVICES", 100_000),
            interval_minutes=_read_positive_integer(
                values,
                "GEOPULSE_INTERVAL_MINUTES",
                15,
            ),
            generator_seed=_read_integer(values, "GEOPULSE_GENERATOR_SEED", 42),
            spark_master=_read_non_empty(
                values,
                "GEOPULSE_SPARK_MASTER",
                "local[*]",
            ),
            shuffle_partitions=_read_positive_integer(
                values,
                "GEOPULSE_SHUFFLE_PARTITIONS",
                200,
            ),
            dbt_target=_read_non_empty(values, "GEOPULSE_DBT_TARGET", "snowflake"),
        )

    @property
    def pings_path(self) -> str:
        """Return the retry-stable input path for the logical processing date."""

        return _templated_path(
            self.data_root,
            "generated",
            RUN_PARTITION_TEMPLATE,
            "mobile_pings.csv.gz",
        )

    @property
    def spatial_output_path(self) -> str:
        """Return the retry-stable Sedona output directory for the logical date."""

        return _templated_path(self.data_root, "output", "spatial", RUN_PARTITION_TEMPLATE)

    def task_environment(self) -> dict[str, str]:
        """Return environment values rendered independently for every Airflow run."""

        return {
            "GEOPULSE_PROJECT_ROOT": str(self.project_root),
            "GEOPULSE_DATA_ROOT": str(self.data_root),
            "GEOPULSE_PYTHON_BIN": self.python_executable,
            "GEOPULSE_DBT_BIN": self.dbt_executable,
            "GEOPULSE_RUN_DATE": PROCESS_DATE_TEMPLATE,
            "GEOPULSE_RUN_PARTITION": RUN_PARTITION_TEMPLATE,
            "GEOPULSE_PINGS_PATH": self.pings_path,
            "GEOPULSE_STORES_PATH": str(self.stores_path),
            "GEOPULSE_SPATIAL_OUTPUT": self.spatial_output_path,
            "GEOPULSE_SPATIAL_MATCHES_PATH": _templated_path(
                Path(self.data_root),
                "output",
                "spatial",
                RUN_PARTITION_TEMPLATE,
                "matches",
            ),
            "GEOPULSE_DBT_PROFILES_DIR": str(self.dbt_profiles_dir),
            "GEOPULSE_DBT_TARGET": self.dbt_target,
        }

    @staticmethod
    def runtime_validation_command() -> str:
        """Return a fast preflight that prevents expensive, predictably doomed runs."""

        return """set -euo pipefail
fail() {
  echo "$1" >&2
  exit "$2"
}
require_executable() {
  if [[ "$1" == */* ]]; then
    [ -x "$1" ] || fail "Required executable is unavailable: $1" 69
  else
    command -v "$1" >/dev/null 2>&1 || fail "Required executable is unavailable: $1" 69
  fi
}
[ -n "${GEOPULSE_WAREHOUSE_LOAD_COMMAND:-}" ] || \
  fail "GEOPULSE_WAREHOUSE_LOAD_COMMAND is required before compute starts." 64
[ -d "$GEOPULSE_PROJECT_ROOT" ] || fail "GeoPulse project root is unavailable." 66
[ -d "$GEOPULSE_DATA_ROOT" ] || fail "GeoPulse data root is unavailable." 66
[ -w "$GEOPULSE_DATA_ROOT" ] || fail "GeoPulse data root is not writable." 73
[ -r "$GEOPULSE_STORES_PATH" ] || fail "Store reference file is unreadable." 66
[ -r "$GEOPULSE_DBT_PROFILES_DIR/profiles.yml" ] || fail "dbt profile is unreadable." 66
require_executable "$GEOPULSE_PYTHON_BIN"
require_executable "$GEOPULSE_DBT_BIN"
echo "GeoPulse runtime configuration validated."
"""

    def generate_command(self) -> str:
        """Build the deterministic, one-day synthetic mobility command."""

        return " ".join(
            (
                shlex.quote(self.python_executable),
                "-m geopulse.synthetic",
                f"--devices {self.devices}",
                "--days 1",
                f"--interval-minutes {self.interval_minutes}",
                f"--seed {self.generator_seed}",
                "--timezone Asia/Kolkata",
                '--start-date "$GEOPULSE_RUN_DATE"',
                '--output "$GEOPULSE_PINGS_PATH"',
            )
        )

    def spatial_join_command(self) -> str:
        """Build the retry-safe Sedona catchment intersection command."""

        return " ".join(
            (
                shlex.quote(self.python_executable),
                "-m geopulse.spatial",
                '--pings "$GEOPULSE_PINGS_PATH"',
                '--stores "$GEOPULSE_STORES_PATH"',
                '--output "$GEOPULSE_SPATIAL_OUTPUT"',
                f"--master {shlex.quote(self.spark_master)}",
                f"--shuffle-partitions {self.shuffle_partitions}",
                "--write-mode overwrite",
            )
        )

    @staticmethod
    def warehouse_load_wrapper_command() -> str:
        """Return a fail-fast wrapper around the deployment-specific publish command."""

        return """set -euo pipefail
if [ -z "${GEOPULSE_WAREHOUSE_LOAD_COMMAND:-}" ]; then
  echo "GEOPULSE_WAREHOUSE_LOAD_COMMAND must publish matches before dbt runs." >&2
  exit 64
fi
bash -euo pipefail -c "$GEOPULSE_WAREHOUSE_LOAD_COMMAND"
"""

    def dbt_build_command(self) -> str:
        """Build and test the production analytics models after warehouse publishing."""

        return " ".join(
            (
                shlex.quote(self.dbt_executable),
                'build --project-dir "$GEOPULSE_PROJECT_ROOT"',
                '--profiles-dir "$GEOPULSE_DBT_PROFILES_DIR"',
                '--target "$GEOPULSE_DBT_TARGET"',
                "--fail-fast",
                "--exclude-resource-type seed",
            )
        )
