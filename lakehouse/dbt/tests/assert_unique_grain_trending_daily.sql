select region, trending_date, count(*)
from {{ ref('gold_trending_daily') }}
group by region, trending_date
having count(*) > 1
