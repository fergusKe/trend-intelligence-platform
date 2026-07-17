"""Bronze 寫入（boto3 put_object，決定性 key + _metadata 信封）。

key 由 Airflow logical_date 導出（非 now()）：重跑同 task = 覆寫同物件 = 冪等（design §3）。
"""
from __future__ import annotations

import json
from datetime import datetime


def bronze_key(prefix: str, region: str, logical_hour: datetime,
               filename: str = "snapshot.json", with_hour: bool = True) -> str:
    parts = [prefix, f"region={region}", f"date={logical_hour:%Y-%m-%d}"]
    if with_hour:
        parts.append(f"hour={logical_hour:%H}")
    parts.append(filename)
    return "/".join(parts)


def build_envelope(response: dict, region: str, logical_hour: datetime, ingested_at: datetime) -> dict:
    return {
        "_metadata": {
            "region": region,
            "logical_hour": logical_hour.isoformat(),
            "ingestion_id": f"{region}_{logical_hour:%Y%m%d%H}",
            "ingested_at": ingested_at.isoformat(),
            "source": "youtube_data_api_v3",
        },
        "response": response,
    }


def make_s3_client(endpoint_url: str | None = None):
    import boto3  # 延遲 import：測試用 FakeS3 不需要 boto3 連線

    return boto3.client("s3", endpoint_url=endpoint_url)


def write_bronze(response: dict, region: str, logical_hour: datetime, ingested_at: datetime,
                 bucket: str, s3_client=None, endpoint_url: str | None = None,
                 prefix: str = "youtube_trending", filename: str = "snapshot.json",
                 with_hour: bool = True) -> str:
    s3 = s3_client if s3_client is not None else make_s3_client(endpoint_url)
    key = bronze_key(prefix, region, logical_hour, filename=filename, with_hour=with_hour)
    body = json.dumps(build_envelope(response, region, logical_hour, ingested_at),
                      ensure_ascii=False)
    s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"),
                  ContentType="application/json")
    return key
