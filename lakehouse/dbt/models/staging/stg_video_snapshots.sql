select
    video_id,
    region,
    captured_at,
    captured_at::date as trending_date,
    title,
    description,
    tags,
    channel_id,
    channel_title,
    category_id,
    published_at,
    coalesce(views, 0) as views,
    coalesce(likes, 0) as likes,
    coalesce(comment_count, 0) as comment_count,
    coalesce(like_ratio, 0) as like_ratio,
    coalesce(engagement_rate, 0) as engagement_rate,
    thumbnail_url,
    ingestion_id,
    ingested_at
from {{ source('silver', 'video_snapshots') }}
where video_id is not null
