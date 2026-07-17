select video_id, region, captured_at, hours_since_prev
from {{ ref('gold_video_velocity_hourly') }}
where hours_since_prev <= 0
