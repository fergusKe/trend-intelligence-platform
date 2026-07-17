with latest_per_day as (
    select *,
        row_number() over (
            partition by video_id, region, trending_date
            order by captured_at desc
        ) as rn
    from {{ ref('stg_video_snapshots') }}
),
agg as (
    select
        category_id,
        region,
        trending_date,
        count(distinct video_id) as video_count,
        sum(views) as total_views,
        round(avg(engagement_rate)::numeric, 4) as avg_engagement_rate
    from latest_per_day
    where rn = 1
    group by category_id, region, trending_date
)
select
    a.category_id,
    coalesce(c.category_name, a.category_id) as category_name,
    a.region,
    a.trending_date,
    a.video_count,
    a.total_views,
    a.avg_engagement_rate,
    round((a.total_views * 100.0
        / nullif(sum(a.total_views) over (partition by a.region, a.trending_date), 0))::numeric, 2)
        as view_share_pct
from agg a
left join {{ ref('stg_categories') }} c
    on a.category_id = c.category_id and a.region = c.region
