"""共用邏輯（非 DAG 檔）：yt_trending_hourly 與 yt_reprocess_range 都需要 Silver DDL/loader/dbt operator 工廠。

拆成獨立模組而非讓 yt_reprocess_range 直接 `import yt_trending_hourly`——Airflow DagBag 對每個
DAG 檔案用各自獨立、經雜湊的 module name 解析（見 airflow.utils.file.get_unique_dag_module_name），
不會把 dags/ 放進 sys.path 讓檔名可互相 import；若跨檔 import 一個「本身也是 DAG 檔」的模組，
會重新執行其 top-level `with DAG(...) as dag:` 區塊，導致同一 dag_id 被註冊兩次
（DagBag 丟出 AirflowDagDuplicatedIdException）。純函式/常數放在不含 DAG 定義的共用模組即可避開。
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.cncf.kubernetes.secret import Secret

CONFIG_DIR = Path(__file__).parent / "config"
PIPELINE = yaml.safe_load((CONFIG_DIR / "pipeline.yaml").read_text())
IMAGES = yaml.safe_load((CONFIG_DIR / "images.yaml").read_text())


def _pg_password() -> str:
    """從 LAKEHOUSE_PG_DSN 解出密碼（模板 params.pg_password 用；無 env 時回空字串讓 DagBag import 可過）。"""
    dsn = os.environ.get("LAKEHOUSE_PG_DSN", "")
    if not dsn:
        return ""
    return unquote(urlsplit(dsn).password or "")


SILVER_DDL = """CREATE TABLE IF NOT EXISTS silver.video_snapshots (
    video_id text NOT NULL,
    region text NOT NULL,
    captured_at timestamptz NOT NULL,
    title text,
    description text,
    tags text,
    channel_id text,
    channel_title text,
    category_id text,
    published_at timestamptz,
    views bigint,
    likes bigint,
    comment_count bigint,
    like_ratio double precision,
    engagement_rate double precision,
    thumbnail_url text,
    ingestion_id text,
    ingested_at timestamptz,
    PRIMARY KEY (video_id, region, captured_at)
)"""

SILVER_COLUMNS = [
    "video_id", "region", "captured_at", "title", "description", "tags",
    "channel_id", "channel_title", "category_id", "published_at",
    "views", "likes", "comment_count", "like_ratio", "engagement_rate",
    "thumbnail_url", "ingestion_id", "ingested_at",
]

SILVER_UPSERT = f"""INSERT INTO silver.video_snapshots ({", ".join(SILVER_COLUMNS)}) VALUES %s
ON CONFLICT (video_id, region, captured_at) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in SILVER_COLUMNS if c not in ("video_id", "region", "captured_at"))}"""


def load_hours_to_postgres(start, end) -> int:
    """pyiceberg 掃 [start, end]（UTC 小時）→ psycopg2 execute_values UPSERT（ga4 extractor 模式）。"""
    import psycopg2
    from psycopg2.extras import execute_values
    from pyiceberg.catalog import load_catalog
    from pyiceberg.expressions import And, GreaterThanOrEqual, LessThanOrEqual

    dsn = os.environ["LAKEHOUSE_PG_DSN"]
    catalog = load_catalog(
        "lakehouse",
        **{
            "type": "sql",
            "uri": dsn.replace("postgresql://", "postgresql+psycopg2://", 1),
            "warehouse": "s3a://silver/warehouse",
            "s3.endpoint": PIPELINE["s3_endpoint"],
            "s3.access-key-id": os.environ["AWS_ACCESS_KEY_ID"],
            "s3.secret-access-key": os.environ["AWS_SECRET_ACCESS_KEY"],
        },
    )
    tbl = catalog.load_table("silver.video_snapshots")
    fmt = "%Y-%m-%dT%H:%M:%S+00:00"
    scan = tbl.scan(row_filter=And(
        GreaterThanOrEqual("captured_at", start.strftime(fmt)),
        LessThanOrEqual("captured_at", end.strftime(fmt)),
    ))
    records = scan.to_arrow().to_pylist()
    rows = [tuple(r[c] for c in SILVER_COLUMNS) for r in records]
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(SILVER_DDL)
            if rows:
                execute_values(cur, SILVER_UPSERT, rows, page_size=500)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def make_dbt_operator(task_id: str, shell_command: str) -> KubernetesPodOperator:
    return KubernetesPodOperator(
        task_id=task_id,
        namespace="data",
        image=f"{IMAGES['dbt']['repository']}:{IMAGES['dbt']['tag']}",
        cmds=["/bin/sh", "-c"],
        arguments=[shell_command],
        secrets=[Secret(deploy_type="env", deploy_target="DBT_PG_PASSWORD",
                        secret="lakehouse-postgres", key="dbt-password")],
        get_logs=True,
        on_finish_action="delete_pod",
        container_resources={
            "requests": {"cpu": "100m", "memory": "256Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
    )
