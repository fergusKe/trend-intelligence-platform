select video_id, region, captured_at, count(*)
from {{ ref('gold_video_velocity_hourly') }}
group by video_id, region, captured_at
having count(*) > 1
