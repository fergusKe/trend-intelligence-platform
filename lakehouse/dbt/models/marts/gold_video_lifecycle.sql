with snapshots as (
    select *,
        row_number() over (partition by video_id, region order by captured_at desc) as rn_desc,
        row_number() over (partition by video_id, region order by captured_at asc) as rn_asc
    from {{ ref('stg_video_snapshots') }}
),
bounds as (
    select
        video_id, region,
        min(captured_at) as first_seen_at,
        max(captured_at) as last_seen_at,
        count(*) as snapshots_count,
        round((extract(epoch from (max(captured_at) - min(captured_at))) / 3600.0)::numeric, 2)
            as hours_on_chart,
        round(avg(engagement_rate)::numeric, 4) as avg_engagement_rate
    from snapshots
    group by video_id, region
),
first_snap as (
    select video_id, region, views as first_views from snapshots where rn_asc = 1
),
last_snap as (
    select video_id, region, title, description, tags, channel_id, channel_title,
           category_id, published_at, views as latest_views
    from snapshots where rn_desc = 1
),
peak as (
    select video_id, region, max(delta_views_per_hour) as peak_delta_views_per_hour
    from {{ ref('gold_video_velocity_hourly') }}
    group by video_id, region
)
select
    b.video_id,
    b.region,
    l.title,
    l.description,
    l.tags,
    l.channel_id,
    l.channel_title,
    l.category_id,
    coalesce(c.category_name, l.category_id) as category_name,
    l.published_at,
    b.first_seen_at,
    b.last_seen_at,
    b.snapshots_count,
    b.hours_on_chart,
    f.first_views,
    l.latest_views,
    l.latest_views - f.first_views as total_views_gained,
    p.peak_delta_views_per_hour,
    b.avg_engagement_rate
from bounds b
join last_snap l using (video_id, region)
join first_snap f using (video_id, region)
left join peak p using (video_id, region)
left join {{ ref('stg_categories') }} c
    on l.category_id = c.category_id and b.region = c.region
