"""Bronze（原始 JSON 信封）→ Iceberg Silver lakehouse.silver.video_snapshots。

- 顯式 schema（關推斷）；一物件一檔 → multiLine=true
- 去重鍵 (video_id, region, captured_at)——保小時粒度（velocity 命脈，design §5）
- overwritePartitions：重跑同小時 = 覆寫該分區 = 冪等
- 兩模式：--date/--hour（hourly）或 --start-hour/--end-hour（reprocess 範圍，UTC ISO 小時含端點）
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from pyspark.sql import DataFrame, SparkSession, functions as F
from pyspark.sql.types import ArrayType, LongType, StringType, StructField, StructType
from pyspark.sql.window import Window

ENVELOPE_SCHEMA = StructType([
    StructField("_metadata", StructType([
        StructField("region", StringType()),
        StructField("logical_hour", StringType()),
        StructField("ingestion_id", StringType()),
        StructField("ingested_at", StringType()),
        StructField("source", StringType()),
    ])),
    StructField("response", StructType([
        StructField("items", ArrayType(StructType([
            StructField("id", StringType()),
            StructField("snippet", StructType([
                StructField("publishedAt", StringType()),
                StructField("channelId", StringType()),
                StructField("title", StringType()),
                StructField("description", StringType()),
                StructField("thumbnails", StructType([
                    StructField("high", StructType([StructField("url", StringType())])),
                ])),
                StructField("channelTitle", StringType()),
                StructField("tags", ArrayType(StringType())),
                StructField("categoryId", StringType()),
            ])),
            StructField("statistics", StructType([
                StructField("viewCount", StringType()),
                StructField("likeCount", StringType()),
                StructField("commentCount", StringType()),
            ])),
            StructField("contentDetails", StructType([
                StructField("duration", StringType()),
            ])),
        ]))),
    ])),
])

SILVER_COLUMNS = [
    "video_id", "region", "captured_at", "title", "description", "tags",
    "channel_id", "channel_title", "category_id", "published_at",
    "views", "likes", "comment_count", "like_ratio", "engagement_rate",
    "thumbnail_url", "ingestion_id", "ingested_at",
]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lakehouse.silver.video_snapshots (
    video_id string, region string, captured_at timestamp,
    title string, description string, tags string,
    channel_id string, channel_title string, category_id string,
    published_at timestamp,
    views bigint, likes bigint, comment_count bigint,
    like_ratio double, engagement_rate double,
    thumbnail_url string, ingestion_id string, ingested_at timestamp
) USING iceberg
PARTITIONED BY (region, hours(captured_at))
"""

HOUR_FMT = "%Y-%m-%dT%H"


def hours_from_args(date: str | None, hour: str | None,
                    start_hour: str | None, end_hour: str | None) -> list[datetime]:
    if date and hour is not None:
        return [datetime.strptime(f"{date}T{hour}", HOUR_FMT).replace(tzinfo=timezone.utc)]
    start = datetime.strptime(start_hour, HOUR_FMT).replace(tzinfo=timezone.utc)
    end = datetime.strptime(end_hour, HOUR_FMT).replace(tzinfo=timezone.utc)
    if end < start:
        raise ValueError(f"end {end} < start {start}")
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += timedelta(hours=1)
    return out


def bronze_paths(hours: list[datetime]) -> list[str]:
    return [
        f"s3a://bronze/youtube_trending/region=*/date={h:%Y-%m-%d}/hour={h:%H}/*.json"
        for h in hours
    ]


def read_bronze(spark: SparkSession, paths: list[str]) -> DataFrame:
    # multiLine：一 bronze 物件 = 一整個 JSON document（非 JSON lines）
    return spark.read.schema(ENVELOPE_SCHEMA).option("multiLine", "true").json(paths)


def transform(df: DataFrame) -> DataFrame:
    items = df.select(
        F.col("_metadata.region").alias("region"),
        F.col("_metadata.ingestion_id").alias("ingestion_id"),
        F.to_timestamp("_metadata.ingested_at").alias("ingested_at"),
        F.explode("response.items").alias("item"),
    )
    out = items.select(
        F.col("item.id").alias("video_id"),
        "region",
        F.date_trunc("hour", F.col("ingested_at")).alias("captured_at"),
        F.col("item.snippet.title").alias("title"),
        F.col("item.snippet.description").alias("description"),
        F.array_join(F.col("item.snippet.tags"), ",").alias("tags"),
        F.col("item.snippet.channelId").alias("channel_id"),
        F.col("item.snippet.channelTitle").alias("channel_title"),
        F.col("item.snippet.categoryId").alias("category_id"),
        F.to_timestamp(F.col("item.snippet.publishedAt")).alias("published_at"),
        F.coalesce(F.col("item.statistics.viewCount").cast(LongType()), F.lit(0)).alias("views"),
        F.coalesce(F.col("item.statistics.likeCount").cast(LongType()), F.lit(0)).alias("likes"),
        F.coalesce(F.col("item.statistics.commentCount").cast(LongType()), F.lit(0)).alias("comment_count"),
        F.col("item.snippet.thumbnails.high.url").alias("thumbnail_url"),
        "ingestion_id",
        "ingested_at",
    ).where(F.col("video_id").isNotNull())
    out = out.withColumn(
        "like_ratio",
        F.when(F.col("views") > 0, F.col("likes") / F.col("views")).otherwise(F.lit(0.0)),
    ).withColumn(
        "engagement_rate",
        F.when(F.col("views") > 0,
               (F.col("likes") + F.col("comment_count")) / F.col("views")).otherwise(F.lit(0.0)),
    )
    w = Window.partitionBy("video_id", "region", "captured_at").orderBy(F.col("ingested_at").desc())
    out = out.withColumn("_rn", F.row_number().over(w)).where(F.col("_rn") == 1).drop("_rn")
    return out.select(*SILVER_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--hour")
    parser.add_argument("--start-hour", dest="start_hour")
    parser.add_argument("--end-hour", dest="end_hour")
    args = parser.parse_args()
    hours = hours_from_args(args.date, args.hour, args.start_hour, args.end_hour)

    spark = SparkSession.builder.appName("yt-silver").getOrCreate()
    df = transform(read_bronze(spark, bronze_paths(hours)))
    spark.sql(CREATE_TABLE_SQL)
    df.writeTo("lakehouse.silver.video_snapshots").overwritePartitions()
    spark.stop()


if __name__ == "__main__":
    main()
