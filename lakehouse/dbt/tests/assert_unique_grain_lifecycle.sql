select video_id, region, count(*)
from {{ ref('gold_video_lifecycle') }}
group by video_id, region
having count(*) > 1
