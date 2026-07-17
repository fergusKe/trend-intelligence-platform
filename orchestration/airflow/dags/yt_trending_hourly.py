"""主管線：ingest ×8（動態映射）→ Spark Bronze→Silver → loader → dbt run → dbt test（DQ gate）。"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.providers.cncf.kubernetes.operators.spark_kubernetes import SparkKubernetesOperator
from airflow.sdk import DAG, get_current_context, task
from airflow.sdk.exceptions import AirflowFailException

# DagBag 對每個 DAG 檔用獨立雜湊 module name 解析，dags/ 不會自動進 sys.path
# （只有 BundleDagBag 這條生產路徑才會）；本機把 dags/ 加進 sys.path 讓同層
# 共用模組 `_yt_common` 可被 import（design 假設落地時的必要修正，見 _yt_common.py docstring）。
sys.path.insert(0, str(Path(__file__).parent))
from _yt_common import IMAGES, PIPELINE, _pg_password, load_hours_to_postgres, make_dbt_operator, resolve_run_anchor  # noqa: E402

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(minutes=10),
}


# max_active_tis_per_dag=3：ingest 動態映射 8 區，KubernetesExecutor 每個 map 起一顆 worker pod；
# 8 顆同時噴會把 16GiB M4 host（單顆 OrbStack VM 承載 kind 三節點 + Postgres/MinIO/kube-prometheus-stack）
# 壓到 swap 狂抖、airflow 全組件探針 20s 逾時、scheduler CrashLoop（見 errata §F-2）。限 3 顆同時仍抓滿
# 8 區（regions=8 資料合約不變，只是分批），削峰值記憶體。context7 查證：@task(max_active_tis_per_dag=N)
# 限制 mapped task 跨 DagRun 的同時執行數（Airflow 3.x dynamic-task-mapping）。
@task(max_active_tis_per_dag=3)
def ingest_trending(region: str) -> str:
    from yt_ingest.bronze import write_bronze
    from yt_ingest.client import QuotaExceededError, YouTubeClient

    ctx = get_current_context()
    # 時間錨走 resolve_run_anchor（排程用 data_interval_start；手動觸發 Airflow 3.x 該欄可能為
    # None，退 dag_run.run_after），再 start_of("hour") 截整點，讓 bronze _metadata.logical_hour
    # 本身即為整點、跨 3 個 task（此處 / delete_stale_sparkapp / load_silver_to_postgres）一致。
    logical_hour = resolve_run_anchor(ctx).start_of("hour")
    client = YouTubeClient(api_key=os.environ["YOUTUBE_API_KEY"])
    try:
        resp = client.fetch_trending(region=region, max_results=PIPELINE["max_results"])
    except QuotaExceededError as exc:
        # fail-fast：重試燒 quota 又必然再失敗（design §3）
        raise AirflowFailException(f"YouTube quota exhausted for {region}: {exc}") from exc
    return write_bronze(
        response=resp, region=region, logical_hour=logical_hour,
        ingested_at=pendulum.now("UTC"),
        bucket=PIPELINE["bronze_bucket"], endpoint_url=PIPELINE["s3_endpoint"],
    )


@task(trigger_rule="all_done")
def delete_stale_sparkapp():
    """重跑同 logical hour 先刪同名舊 SparkApplication（operator 對同名 apply 會拒，design §5）。"""
    from kubernetes import client, config

    ctx = get_current_context()
    name = "yt-silver-" + resolve_run_anchor(ctx).start_of("hour").strftime("%Y%m%d%H")
    config.load_incluster_config()
    api = client.CustomObjectsApi()
    try:
        api.delete_namespaced_custom_object(
            group="sparkoperator.k8s.io", version="v1beta2",
            namespace="data", plural="sparkapplications", name=name,
        )
    except client.exceptions.ApiException as exc:
        if exc.status != 404:  # 404 = 無舊 app，正常
            raise


@task
def load_silver_to_postgres() -> int:
    ctx = get_current_context()
    # [hour,hour] 掃描窗須與 ingest/Spark 寫入的整點 captured_at 對齊，否則 n==0 guard 必炸——
    # 走同一支 resolve_run_anchor(ctx).start_of("hour")（手動觸發 data_interval_start 可能為 None，
    # 見 _yt_common.resolve_run_anchor），確保三 task 取到同一乾淨整點。
    hour = resolve_run_anchor(ctx).start_of("hour")
    n = load_hours_to_postgres(hour, hour)
    if n == 0:
        raise RuntimeError(f"silver scan 為空（hour={hour.isoformat()}）——Spark 未產出？")
    return n


with DAG(
    dag_id="yt_trending_hourly",
    schedule="0 * * * *",
    start_date=pendulum.datetime(2026, 7, 1, tz="UTC"),
    catchup=False,   # mostPopular 無歷史，catchup 是資料謊言（design §7）——永遠不開
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=45),
    default_args=DEFAULT_ARGS,
    tags=["p1", "youtube"],
) as dag:
    ingest = ingest_trending.expand(region=PIPELINE["regions"])

    spark = SparkKubernetesOperator(
        task_id="spark_bronze_to_silver",
        namespace="data",
        application_file="templates/spark_silver.yaml",
        params={
            "spark_image": f"{IMAGES['spark_job']['repository']}:{IMAGES['spark_job']['tag']}",
            "pg_password": _pg_password(),
        },
    )

    dbt_run = make_dbt_operator("dbt_run", "dbt run --profiles-dir /app --project-dir /app")
    dbt_test = make_dbt_operator(
        "dbt_test",
        "dbt source freshness --profiles-dir /app --project-dir /app && dbt test --profiles-dir /app --project-dir /app",
    )

    ingest >> delete_stale_sparkapp() >> spark >> load_silver_to_postgres() >> dbt_run >> dbt_test
