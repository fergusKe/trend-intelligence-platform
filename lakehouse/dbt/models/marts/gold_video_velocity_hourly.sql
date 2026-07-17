with deltas as (
    select
        video_id, title, channel_title, region, captured_at,
        views, likes, comment_count,
        lag(views) over w as prev_views,
        lag(likes) over w as prev_likes,
        lag(comment_count) over w as prev_comments,
        lag(captured_at) over w as prev_captured_at
    from {{ ref('stg_video_snapshots') }}
    window w as (partition by video_id, region order by captured_at)
),
calc as (
    select
        video_id, title, channel_title, region, captured_at, views,
        views - prev_views as delta_views,
        likes - prev_likes as delta_likes,
        comment_count - prev_comments as delta_comments,
        round((extract(epoch from (captured_at - prev_captured_at)) / 3600.0)::numeric, 2)
            as hours_since_prev,
        prev_views
    from deltas
    where prev_views is not null
)
select
    video_id, title, channel_title, region, captured_at, views,
    delta_views, delta_likes, delta_comments,
    hours_since_prev,
    round((delta_views / nullif(hours_since_prev, 0))::numeric, 2) as delta_views_per_hour,
    case when prev_views = 0 then null
         else round((delta_views * 100.0 / prev_views)::numeric, 2)
    end as delta_views_pct,
    rank() over (
        partition by region, captured_at
        order by (delta_views / nullif(hours_since_prev, 0)) desc nulls last
    ) as velocity_rank
from calc
