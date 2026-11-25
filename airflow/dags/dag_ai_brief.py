"""Generate the airspace brief every 15 minutes."""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator


def _run_brief() -> dict:
    from src.ai.brief import run
    return run(window_minutes=15)


def _run_kinematic_sync() -> dict:
    from src.ai.kinematic_vectors import sync_recent_anomalies
    return sync_recent_anomalies(hours=2, limit=2000)


with DAG(
    dag_id="dag_ai_brief",
    start_date=datetime(2026, 1, 1),
    schedule="*/15 * * * *",         # ← was "0 * * * *"
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    is_paused_upon_creation=False,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "owner": "aeropulse",
    },
    tags=["ai", "brief"],
) as dag:
    sync_vectors = PythonOperator(
        task_id="sync_kinematic_vectors",
        python_callable=_run_kinematic_sync,
    )
    generate_brief = PythonOperator(
        task_id="generate_brief",
        python_callable=_run_brief,
    )