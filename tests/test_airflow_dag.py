from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

AIRFLOW_AVAILABLE = importlib.util.find_spec("airflow") is not None


@unittest.skipUnless(AIRFLOW_AVAILABLE, "install the orchestration extra to validate the DAG")
class AirflowDagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.original_environment = {
            key: os.environ.get(key)
            for key in ("AIRFLOW__CORE__LOAD_EXAMPLES", "GEOPULSE_PROJECT_ROOT")
        }
        os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
        os.environ["GEOPULSE_PROJECT_ROOT"] = str(cls.project_root)

        from airflow.models import DagBag

        cls.dag_bag = DagBag(dag_folder=str(cls.project_root / "dags"))

    @classmethod
    def tearDownClass(cls) -> None:
        for key, value in cls.original_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_dag_imports_without_errors(self) -> None:
        self.assertEqual(self.dag_bag.import_errors, {})
        self.assertIn("geopulse_daily_pipeline", self.dag_bag.dags)

    def test_dag_schedule_and_concurrency_are_bounded(self) -> None:
        from airflow.sdk import CronDataIntervalTimetable

        dag = self.dag_bag.dags["geopulse_daily_pipeline"]

        self.assertIsNotNone(dag)
        self.assertFalse(dag.catchup)
        self.assertEqual(dag.max_active_runs, 1)
        self.assertEqual(str(dag.timezone), "Asia/Kolkata")
        self.assertIsInstance(dag.schedule, CronDataIntervalTimetable)
        self.assertEqual(dag.schedule.expression, "0 2 * * *")

    def test_task_graph_enforces_publish_before_dbt(self) -> None:
        dag = self.dag_bag.dags["geopulse_daily_pipeline"]
        expected_chain = (
            "validate_runtime_configuration",
            "generate_daily_pings",
            "run_sedona_spatial_join",
            "load_spatial_matches",
            "build_dbt_analytics",
        )

        self.assertEqual(set(dag.task_ids), set(expected_chain))
        for upstream_id, downstream_id in zip(expected_chain[:-1], expected_chain[1:], strict=True):
            self.assertEqual(dag.get_task(upstream_id).downstream_task_ids, {downstream_id})
            self.assertEqual(dag.get_task(downstream_id).upstream_task_ids, {upstream_id})

    def test_tasks_use_logical_date_paths_and_fail_fast_publish_boundary(self) -> None:
        dag = self.dag_bag.dags["geopulse_daily_pipeline"]
        validation_task = dag.get_task("validate_runtime_configuration")
        generate_task = dag.get_task("generate_daily_pings")
        spatial_task = dag.get_task("run_sedona_spatial_join")
        load_task = dag.get_task("load_spatial_matches")
        dbt_task = dag.get_task("build_dbt_analytics")

        self.assertIn("required before compute starts", validation_task.bash_command)
        self.assertTrue(validation_task.append_env)
        self.assertIn("data_interval_start", generate_task.env["GEOPULSE_RUN_DATE"])
        self.assertIn("data_interval_start", spatial_task.env["GEOPULSE_SPATIAL_OUTPUT"])
        self.assertIn("must publish", load_task.bash_command)
        self.assertNotIn("GEOPULSE_WAREHOUSE_LOAD_COMMAND", load_task.env)
        self.assertTrue(load_task.append_env)
        self.assertIn("dbt", dbt_task.bash_command)
        self.assertIn("--exclude-resource-type seed", dbt_task.bash_command)
        self.assertTrue(all(task.do_xcom_push is False for task in dag.tasks))

    def test_logical_date_templates_render_to_one_stable_partition(self) -> None:
        import pendulum

        dag = self.dag_bag.dags["geopulse_daily_pipeline"]
        task = dag.get_task("generate_daily_pings")
        rendered_environment = task.render_template(
            task.env,
            {
                "data_interval_start": pendulum.datetime(
                    2026,
                    9,
                    26,
                    2,
                    0,
                    tz="Asia/Kolkata",
                )
            },
            jinja_env=dag.get_template_env(),
        )

        self.assertEqual(rendered_environment["GEOPULSE_RUN_DATE"], "2026-09-26")
        self.assertEqual(rendered_environment["GEOPULSE_RUN_PARTITION"], "20260926")
        self.assertEqual(
            rendered_environment["GEOPULSE_PINGS_PATH"],
            str(self.project_root / "data/generated/20260926/mobile_pings.csv.gz"),
        )


if __name__ == "__main__":
    unittest.main()
