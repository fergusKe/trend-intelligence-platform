"""Categories 維度 → Postgres silver.youtube_categories UPSERT（維度小，不過 Spark/Iceberg——刻意決定，design §3）。"""
from __future__ import annotations

CATEGORIES_DDL = """CREATE TABLE IF NOT EXISTS silver.youtube_categories (
    category_id text NOT NULL,
    region text NOT NULL,
    category_name text,
    updated_at timestamptz,
    PRIMARY KEY (category_id, region)
)"""

CATEGORIES_UPSERT = """INSERT INTO silver.youtube_categories (category_id, region, category_name, updated_at)
VALUES (%s, %s, %s, %s)
ON CONFLICT (category_id, region) DO UPDATE SET
    category_name = EXCLUDED.category_name,
    updated_at = EXCLUDED.updated_at"""


def rows_from_response(response: dict, region: str, updated_at: str) -> list[tuple]:
    return [
        (item["id"], region, item.get("snippet", {}).get("title"), updated_at)
        for item in response.get("items", [])
    ]


def upsert_categories(conn, response: dict, region: str, updated_at: str) -> int:
    rows = rows_from_response(response, region, updated_at)
    with conn.cursor() as cur:
        cur.execute(CATEGORIES_DDL)
        cur.executemany(CATEGORIES_UPSERT, rows)
    conn.commit()
    return len(rows)


def connect(dsn: str):
    import psycopg2  # 延遲 import：單元測試用 FakeConn

    return psycopg2.connect(dsn)
