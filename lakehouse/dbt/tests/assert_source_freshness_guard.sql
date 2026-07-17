-- 與 source freshness 雙保險；這條在 dbt test 內直接擋 DAG
select max(ingested_at) as last_ingested_at
from {{ source('silver', 'video_snapshots') }}
having now() - max(ingested_at) > interval '4 hours'
