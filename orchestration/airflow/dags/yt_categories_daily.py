"""Categories 維度 @daily：fetch ×8 → bronze（決定性 key）→ UPSERT silver.youtube_categories（不過 Spark，刻意）。"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pendulum
import yaml
from airflow.sdk import DAG, get_current_context, task
from airflow.sdk.exceptions import AirflowFailException

CONFIG_DIR = Path(__file__).parent / "config"
PIPELINE = yaml.safe_load((CONFIG_DIR / "pipeline.yaml").read_text())

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(minutes=10),
}


@task
def ingest_categories(region: str) -> int:
    from yt_ingest.bronze import write_bronze
    from yt_ingest.categories import connect, upsert_categories
    from yt_ingest.client import QuotaExceededError, YouTubeClient

    ctx = get_current_context()
    logical_date = ctx["data_interval_start"]
    client = YouTubeClient(api_key=os.environ["YOUTUBE_API_KEY"])
    try:
        resp = client.fetch_categories(region=region)
    except QuotaExceededError as exc:
        raise AirflowFailException(f"YouTube quota exhausted for {region}: {exc}") from exc
    write_bronze(
        response=resp, region=region, logical_hour=logical_date,
        ingested_at=pendulum.now("UTC"),
        bucket=PIPELINE["bronze_bucket"], endpoint_url=PIPELINE["s3_endpoint"],
        prefix="youtube_categories", filename="categories.json", with_hour=False,
    )
    conn = connect(os.environ["LAKEHOUSE_PG_DSN"])
    try:
        return upsert_categories(conn, resp, region=region,
                                 updated_at=pendulum.now("UTC").isoformat())
    finally:
        conn.close()


with DAG(
    dag_id="yt_categories_daily",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 7, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    default_args=DEFAULT_ARGS,
    tags=["p1", "youtube"],
) as dag:
    ingest_categories.expand(region=PIPELINE["regions"])
