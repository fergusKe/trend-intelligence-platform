"""手動重處理（bronze 已有 → Silver/Gold 重算）：params start_hour/end_hour（UTC ISO 小時，含端點，如 2026-07-08T14）。
冪等由 overwritePartitions（Spark）與 UPSERT（loader）保證；ingest 不重跑（mostPopular 無歷史）。"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pendulum
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator
from airflow.sdk import DAG, Param, get_current_context, task

# 見 yt_trending_hourly.py 同段註解：共用模組需要 dags/ 在 sys.path 才能 import。
sys.path.insert(0, str(Path(__file__).parent))
from _yt_common import IMAGES, _pg_password, load_hours_to_postgres, make_dbt_operator  # noqa: E402

HOUR_FMT = "%Y-%m-%dT%H"


def _parse_hour(value: str) -> datetime:
    return datetime.strptime(value, HOUR_FMT).replace(tzinfo=timezone.utc)


@task
def load_range_to_postgres() -> int:
    ctx = get_current_context()
    start = _parse_hour(ctx["params"]["start_hour"])
    end = _parse_hour(ctx["params"]["end_hour"])
    if end < start:
        raise ValueError(f"end_hour {end} 早於 start_hour {start}")
    return load_hours_to_postgres(start, end)


with DAG(
    dag_id="yt_reprocess_range",
    schedule=None,
    start_date=pendulum.datetime(2026, 7, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=120),
    params={
        "start_hour": Param(type="string", description="UTC ISO 小時（含端點），如 2026-07-08T14"),
        "end_hour": Param(type="string", description="UTC ISO 小時（含端點）"),
    },
    default_args={
        "retries": 1,
        "retry_delay": timedelta(minutes=1),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=10),
        "execution_timeout": timedelta(minutes=60),
    },
    tags=["p1", "youtube", "manual"],
) as dag:
    spark = SparkKubernetesOperator(
        task_id="spark_reprocess_range",
        namespace="data",
        application_file="templates/spark_silver.yaml",
        params={
            "spark_image": f"{IMAGES['spark_job']['repository']}:{IMAGES['spark_job']['tag']}",
            "pg_password": _pg_password(),
            # start_hour/end_hour 由 dag params 進 Jinja context（模板 reprocess 分支）
        },
    )
    dbt_run = make_dbt_operator("dbt_run", "dbt run --profiles-dir /app --project-dir /app")
    dbt_test = make_dbt_operator(
        "dbt_test",
        "dbt source freshness --profiles-dir /app --project-dir /app && dbt test --profiles-dir /app --project-dir /app",
    )
    spark >> load_range_to_postgres() >> dbt_run >> dbt_test
