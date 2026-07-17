with latest_snapshot as (
    select *,
        row_number() over (partition by video_id, region order by captured_at desc) as rn
    from {{ ref('stg_video_snapshots') }}
),
per_video as (
    select * from latest_snapshot where rn = 1
),
days as (
    select channel_id, region, count(distinct trending_date) as days_on_chart
    from {{ ref('stg_video_snapshots') }}
    group by channel_id, region
),
agg as (
    select
        channel_id,
        max(channel_title) as channel_title,
        region,
        count(distinct video_id) as videos_trended,
        sum(views) as total_views,
        round(avg(engagement_rate)::numeric, 4) as avg_engagement_rate,
        string_agg(distinct category_id, ',') as categories
    from per_video
    group by channel_id, region
)
select
    a.channel_id,
    a.channel_title,
    a.region,
    a.videos_trended,
    a.total_views,
    a.avg_engagement_rate,
    d.days_on_chart,
    rank() over (partition by a.region order by a.total_views desc) as rank_in_region,
    a.categories
from agg a
join days d using (channel_id, region)
