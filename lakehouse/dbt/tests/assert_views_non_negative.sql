select video_id, region, captured_at, views, likes, comment_count
from {{ ref('stg_video_snapshots') }}
where views < 0 or likes < 0 or comment_count < 0
