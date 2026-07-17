select
    category_id,
    region,
    category_name,
    updated_at
from {{ source('silver', 'youtube_categories') }}
