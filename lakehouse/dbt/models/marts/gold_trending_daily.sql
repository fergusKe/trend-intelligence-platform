with latest_per_day as (
    select *,
        row_number() over (
            partition by video_id, region, trending_date
            order by captured_at desc
        ) as rn
    from {{ ref('stg_video_snapshots') }}
)
select
    region,
    trending_date,
    count(distinct video_id) as total_videos,
    sum(views) as total_views,
    sum(likes) as total_likes,
    round(avg(views)::numeric, 0) as avg_views_per_video,
    round(avg(like_ratio)::numeric, 4) as avg_like_ratio,
    round(avg(engagement_rate)::numeric, 4) as avg_engagement_rate,
    count(distinct channel_id) as unique_channels,
    count(distinct category_id) as unique_categories
from latest_per_day
where rn = 1
group by region, trending_date
