from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from geopulse.orchestration import (
    PROCESS_DATE_TEMPLATE,
    RUN_PARTITION_TEMPLATE,
    DailyPipelineConfig,
)


class DailyPipelineConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name).resolve()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_defaults_target_daily_ten_million_row_scale(self) -> None:
        config = DailyPipelineConfig.from_environment(self.project_root, {})

        self.assertEqual(config.devices, 100_000)
        self.assertEqual(config.interval_minutes, 15)
        self.assertEqual(config.devices * (1_440 // config.interval_minutes), 9_600_000)
        self.assertEqual(config.data_root, self.project_root / "data")
        self.assertEqual(config.stores_path, self.project_root / "data/reference/stores.csv")
        self.assertEqual(config.dbt_profiles_dir, self.project_root / "profiles/snowflake")
        self.assertEqual(config.dbt_target, "snowflake")

    def test_environment_overrides_are_validated_and_resolved(self) -> None:
        config = DailyPipelineConfig.from_environment(
            self.project_root,
            {
                "GEOPULSE_DATA_ROOT": "shared-data",
                "GEOPULSE_STORES_PATH": "config/stores.csv",
                "GEOPULSE_DBT_PROFILES_DIR": "profiles/ci",
                "GEOPULSE_DBT_TARGET": "ci",
                "GEOPULSE_DEVICES": "250",
                "GEOPULSE_INTERVAL_MINUTES": "60",
                "GEOPULSE_GENERATOR_SEED": "7",
                "GEOPULSE_SPARK_MASTER": "spark://cluster:7077",
                "GEOPULSE_SHUFFLE_PARTITIONS": "16",
            },
        )

        self.assertEqual(config.data_root, self.project_root / "shared-data")
        self.assertEqual(config.stores_path, self.project_root / "config/stores.csv")
        self.assertEqual(config.dbt_profiles_dir, self.project_root / "profiles/ci")
        self.assertEqual(config.devices, 250)
        self.assertEqual(config.interval_minutes, 60)
        self.assertEqual(config.generator_seed, 7)
        self.assertEqual(config.spark_master, "spark://cluster:7077")
        self.assertEqual(config.shuffle_partitions, 16)

    def test_invalid_numeric_environment_values_fail_during_dag_parse(self) -> None:
        invalid_cases = (
            ({"GEOPULSE_DEVICES": "many"}, "GEOPULSE_DEVICES must be an integer"),
            ({"GEOPULSE_DEVICES": "0"}, "GEOPULSE_DEVICES must be greater than zero"),
            (
                {"GEOPULSE_INTERVAL_MINUTES": "17"},
                "interval_minutes must be a positive divisor of 1440",
            ),
            (
                {"GEOPULSE_SHUFFLE_PARTITIONS": "-1"},
                "GEOPULSE_SHUFFLE_PARTITIONS must be greater than zero",
            ),
        )

        for environment, message in invalid_cases:
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(ValueError, message):
                    DailyPipelineConfig.from_environment(self.project_root, environment)

    def test_run_paths_are_partitioned_by_airflow_data_interval(self) -> None:
        config = DailyPipelineConfig.from_environment(self.project_root, {})
        environment = config.task_environment()

        self.assertEqual(environment["GEOPULSE_RUN_DATE"], PROCESS_DATE_TEMPLATE)
        self.assertEqual(environment["GEOPULSE_RUN_PARTITION"], RUN_PARTITION_TEMPLATE)
        self.assertIn(RUN_PARTITION_TEMPLATE, environment["GEOPULSE_PINGS_PATH"])
        self.assertTrue(environment["GEOPULSE_PINGS_PATH"].endswith("mobile_pings.csv.gz"))
        self.assertIn(RUN_PARTITION_TEMPLATE, environment["GEOPULSE_SPATIAL_OUTPUT"])
        self.assertTrue(environment["GEOPULSE_SPATIAL_MATCHES_PATH"].endswith("matches"))
        self.assertNotIn("GEOPULSE_WAREHOUSE_LOAD_COMMAND", environment)

    def test_commands_preserve_pipeline_contract_and_retry_safety(self) -> None:
        config = DailyPipelineConfig.from_environment(self.project_root, {})

        generate_command = config.generate_command()
        self.assertIn("-m geopulse.synthetic", generate_command)
        self.assertIn("--devices 100000", generate_command)
        self.assertIn('--start-date "$GEOPULSE_RUN_DATE"', generate_command)
        self.assertIn('--output "$GEOPULSE_PINGS_PATH"', generate_command)

        spatial_command = config.spatial_join_command()
        self.assertIn("-m geopulse.spatial", spatial_command)
        self.assertIn('--pings "$GEOPULSE_PINGS_PATH"', spatial_command)
        self.assertIn('--output "$GEOPULSE_SPATIAL_OUTPUT"', spatial_command)
        self.assertIn("--write-mode overwrite", spatial_command)

        publish_command = config.warehouse_load_wrapper_command()
        self.assertIn("GEOPULSE_WAREHOUSE_LOAD_COMMAND must publish", publish_command)
        self.assertIn('bash -euo pipefail -c "$GEOPULSE_WAREHOUSE_LOAD_COMMAND"', publish_command)

        dbt_command = config.dbt_build_command()
        self.assertIn('build --project-dir "$GEOPULSE_PROJECT_ROOT"', dbt_command)
        self.assertIn('--profiles-dir "$GEOPULSE_DBT_PROFILES_DIR"', dbt_command)
        self.assertIn('--target "$GEOPULSE_DBT_TARGET"', dbt_command)
        self.assertIn("--fail-fast", dbt_command)
        self.assertIn("--exclude-resource-type seed", dbt_command)

    @unittest.skipUnless(
        os.name != "nt" and shutil.which("bash") is not None,
        "Bash behavior is validated on Linux CI",
    )
    def test_shell_guards_fail_closed_before_compute(self) -> None:
        data_root = self.project_root / "data"
        stores_path = data_root / "reference/stores.csv"
        profiles_path = self.project_root / "profiles/snowflake/profiles.yml"
        stores_path.parent.mkdir(parents=True)
        stores_path.touch()
        profiles_path.parent.mkdir(parents=True)
        profiles_path.touch()
        config = DailyPipelineConfig.from_environment(
            self.project_root,
            {
                "GEOPULSE_PYTHON_BIN": sys.executable,
                "GEOPULSE_DBT_BIN": sys.executable,
            },
        )
        environment = {
            **os.environ,
            **config.task_environment(),
            "GEOPULSE_SPATIAL_MATCHES_PATH": str(data_root / "matches"),
        }
        environment.pop("GEOPULSE_WAREHOUSE_LOAD_COMMAND", None)

        missing_loader = subprocess.run(
            ["bash", "-c", config.runtime_validation_command()],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(missing_loader.returncode, 64)
        self.assertIn("required before compute starts", missing_loader.stderr)

        environment["GEOPULSE_WAREHOUSE_LOAD_COMMAND"] = "printf publish-ok"
        validated = subprocess.run(
            ["bash", "-c", config.runtime_validation_command()],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertIn("runtime configuration validated", validated.stdout)

        published = subprocess.run(
            ["bash", "-c", config.warehouse_load_wrapper_command()],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertEqual(published.stdout, "publish-ok")


if __name__ == "__main__":
    unittest.main()
