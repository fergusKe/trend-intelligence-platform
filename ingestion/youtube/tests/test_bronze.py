import json
from datetime import datetime, timezone

from yt_ingest.bronze import bronze_key, build_envelope, write_bronze


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})


LOGICAL = datetime(2026, 7, 8, 14, 0, 0, tzinfo=timezone.utc)
INGESTED = datetime(2026, 7, 8, 14, 3, 21, tzinfo=timezone.utc)


def test_bronze_key_is_deterministic_from_logical_hour():
    key = bronze_key("youtube_trending", "TW", LOGICAL)
    assert key == "youtube_trending/region=TW/date=2026-07-08/hour=14/snapshot.json"
    # 同 logical hour 重算 = 同 key（重跑覆寫 = 冪等）
    assert bronze_key("youtube_trending", "TW", LOGICAL) == key


def test_categories_key_layout():
    key = bronze_key("youtube_categories", "TW", LOGICAL, filename="categories.json", with_hour=False)
    assert key == "youtube_categories/region=TW/date=2026-07-08/categories.json"


def test_envelope_fields():
    env = build_envelope({"items": []}, region="TW", logical_hour=LOGICAL, ingested_at=INGESTED)
    md = env["_metadata"]
    assert md["region"] == "TW"
    assert md["logical_hour"] == "2026-07-08T14:00:00+00:00"
    assert md["ingestion_id"] == "TW_2026070814"
    assert md["ingested_at"] == "2026-07-08T14:03:21+00:00"
    assert md["source"] == "youtube_data_api_v3"
    assert env["response"] == {"items": []}


def test_write_bronze_puts_envelope_to_bucket():
    s3 = FakeS3()
    key = write_bronze(
        response={"items": [1]}, region="TW", logical_hour=LOGICAL, ingested_at=INGESTED,
        bucket="bronze", s3_client=s3,
    )
    assert key == "youtube_trending/region=TW/date=2026-07-08/hour=14/snapshot.json"
    put = s3.puts[0]
    assert put["Bucket"] == "bronze"
    assert put["ContentType"] == "application/json"
    body = json.loads(put["Body"])
    assert body["_metadata"]["ingestion_id"] == "TW_2026070814"
    assert body["response"] == {"items": [1]}
