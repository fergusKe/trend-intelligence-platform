import json
import sys
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "jobs"))
from silver_job import ENVELOPE_SCHEMA, SILVER_COLUMNS, hours_from_args, read_bronze, transform  # noqa: E402


@pytest.fixture(scope="session")
def spark():
    s = (SparkSession.builder.master("local[1]").appName("silver-test")
         .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    yield s
    s.stop()


def envelope(region="TW", ingested="2026-07-08T14:03:21+00:00", items=None):
    return {
        "_metadata": {"region": region, "logical_hour": "2026-07-08T14:00:00+00:00",
                       "ingestion_id": f"{region}_2026070814", "ingested_at": ingested,
                       "source": "youtube_data_api_v3"},
        "response": {"items": items if items is not None else [
            {"id": "vid1",
             "snippet": {"publishedAt": "2026-07-01T00:00:00Z", "channelId": "ch1",
                          "title": "t1", "description": "d1",
                          "thumbnails": {"high": {"url": "http://img/1.jpg"}},
                          "channelTitle": "Chan 1", "tags": ["a", "b"], "categoryId": "10"},
             "statistics": {"viewCount": "1000", "likeCount": "100", "commentCount": "50"},
             "contentDetails": {"duration": "PT10M"}},
        ]},
    }


def write_fixture(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return str(p)


def test_transform_columns_and_formulas(spark, tmp_path):
    path = write_fixture(tmp_path, "a.json", envelope())
    df = transform(read_bronze(spark, [path]))
    assert df.columns == SILVER_COLUMNS
    row = df.collect()[0]
    assert row.video_id == "vid1" and row.region == "TW"
    assert row.captured_at.isoformat().startswith("2026-07-08T14:00:00")  # date_trunc hour
    assert row.tags == "a,b"
    assert row.views == 1000 and row.likes == 100 and row.comment_count == 50
    assert row.like_ratio == pytest.approx(0.1)
    assert row.engagement_rate == pytest.approx(0.15)
    assert row.description == "d1"  # 範本漏抓、本設計補上的 P2b 語料欄


def test_zero_views_gives_zero_ratios(spark, tmp_path):
    env = envelope()
    env["response"]["items"][0]["statistics"] = {"viewCount": "0", "likeCount": None, "commentCount": None}
    path = write_fixture(tmp_path, "z.json", env)
    row = transform(read_bronze(spark, [path])).collect()[0]
    assert row.views == 0 and row.likes == 0 and row.comment_count == 0  # fillna(0)
    assert row.like_ratio == 0.0 and row.engagement_rate == 0.0          # views=0 → 0.0


def test_dedupe_keeps_latest_per_video_region_hour(spark, tmp_path):
    # 同 (video_id, region, captured_at 小時) 兩筆（重跑殘留情境）→ 留 ingested_at 較新者
    p1 = write_fixture(tmp_path, "d1.json", envelope(ingested="2026-07-08T14:01:00+00:00"))
    env2 = envelope(ingested="2026-07-08T14:30:00+00:00")
    env2["response"]["items"][0]["statistics"]["viewCount"] = "2000"
    p2 = write_fixture(tmp_path, "d2.json", env2)
    df = transform(read_bronze(spark, [p1, p2]))
    rows = df.collect()
    assert len(rows) == 1
    assert rows[0].views == 2000


def test_empty_input_raises(spark, tmp_path):
    with pytest.raises(Exception):
        read_bronze(spark, [str(tmp_path / "nope" / "*.json")]).collect()


def test_hours_from_args_single_and_range():
    hours = hours_from_args(date="2026-07-08", hour="14", start_hour=None, end_hour=None)
    assert [h.strftime("%Y-%m-%dT%H") for h in hours] == ["2026-07-08T14"]
    hours = hours_from_args(date=None, hour=None, start_hour="2026-07-08T22", end_hour="2026-07-09T01")
    assert [h.strftime("%Y-%m-%dT%H") for h in hours] == [
        "2026-07-08T22", "2026-07-08T23", "2026-07-09T00", "2026-07-09T01"]
