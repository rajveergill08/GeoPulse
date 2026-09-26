"""Daily GeoPulse mobility pipeline for Apache Airflow 3."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, CronDataIntervalTimetable

from geopulse.orchestration import PIPELINE_TIMEZONE, DailyPipelineConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG = DailyPipelineConfig.from_environment(REPOSITORY_ROOT)
TASK_ENVIRONMENT = CONFIG.task_environment()

DEFAULT_ARGS = {
    "owner": "geopulse",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}


with DAG(
    dag_id="geopulse_daily_pipeline",
    description="Generate mobility pings, run Sedona, publish matches, and build dbt marts.",
    schedule=CronDataIntervalTimetable("0 2 * * *", timezone=PIPELINE_TIMEZONE),
    start_date=pendulum.datetime(2026, 9, 26, 2, 0, tz=PIPELINE_TIMEZONE),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=16),
    default_args=DEFAULT_ARGS,
    tags=["geopulse", "mobility", "geospatial"],
) as dag:
    validate_runtime_configuration = BashOperator(
        task_id="validate_runtime_configuration",
        bash_command=CONFIG.runtime_validation_command(),
        cwd=str(CONFIG.project_root),
        env=TASK_ENVIRONMENT,
        append_env=True,
        execution_timeout=timedelta(minutes=5),
        do_xcom_push=False,
    )

    generate_daily_pings = BashOperator(
        task_id="generate_daily_pings",
        bash_command=CONFIG.generate_command(),
        cwd=str(CONFIG.project_root),
        env=TASK_ENVIRONMENT,
        append_env=True,
        execution_timeout=timedelta(hours=3),
        do_xcom_push=False,
    )

    run_sedona_spatial_join = BashOperator(
        task_id="run_sedona_spatial_join",
        bash_command=CONFIG.spatial_join_command(),
        cwd=str(CONFIG.project_root),
        env=TASK_ENVIRONMENT,
        append_env=True,
        execution_timeout=timedelta(hours=10),
        do_xcom_push=False,
    )

    load_spatial_matches = BashOperator(
        task_id="load_spatial_matches",
        bash_command=CONFIG.warehouse_load_wrapper_command(),
        cwd=str(CONFIG.project_root),
        env=TASK_ENVIRONMENT,
        append_env=True,
        execution_timeout=timedelta(hours=2),
        do_xcom_push=False,
    )

    build_dbt_analytics = BashOperator(
        task_id="build_dbt_analytics",
        bash_command=CONFIG.dbt_build_command(),
        cwd=str(CONFIG.project_root),
        env=TASK_ENVIRONMENT,
        append_env=True,
        execution_timeout=timedelta(hours=2),
        do_xcom_push=False,
    )

    (
        validate_runtime_configuration
        >> generate_daily_pings
        >> run_sedona_spatial_join
        >> load_spatial_matches
        >> build_dbt_analytics
    )
