"""Explain the newest anomalies every 5 minutes and index them for similarity."""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator


def _run_explain() -> dict:
    from src.ai.explain import run
    # Small batches: the Pollinations fallback allows ~1 request per 46s.
    return run(batch_size=5, time_budget_sec=240)


with DAG(
    dag_id="dag_explain_anomalies",
    start_date=datetime(2026, 1, 1),
    schedule="*/5 * * * *",
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    is_paused_upon_creation=False,
    default_args={
        "retries": 0,   # the next run is 5 minutes away anyway
        "owner": "aeropulse",
    },
    tags=["ai", "explanation"],
) as dag:
    PythonOperator(task_id="explain_batch", python_callable=_run_explain)