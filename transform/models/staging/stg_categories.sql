-- Staging layer for raw.categories.
--
-- Responsibilities (and ONLY these):
--   1. Strip the HKCategoryTypeIdentifier prefix from category_type → category_name.
--   2. Convert UTC timestamps to America/Chicago.
--   3. Tag each row with a source_priority and keep only the winning source
--      per (category_name, start_ts_local). Per CLAUDE.md:
--        Apple Watch > iPhone > everything else.
--
-- No business logic lives here — that's intermediate/marts.

with ranked as (
    select
        regexp_replace(category_type, '^HKCategoryTypeIdentifier', '') as category_name,
        category_value,
        source_name,
        source_version,
        product_type,
        device,
        (start_ts at time zone 'America/Chicago')::timestamp as start_ts_local,
        (end_ts   at time zone 'America/Chicago')::timestamp as end_ts_local,
        hk_time_zone,
        hk_heart_rate_threshold,
        case
            when source_name ilike '%apple watch%' then 1
            when source_name ilike '%iphone%'      then 2
            else 3
        end as source_priority,
        source_file,
        source_sha256,
        row_number() over (
            partition by category_type, start_ts
            order by
                case
                    when source_name ilike '%apple watch%' then 1
                    when source_name ilike '%iphone%'      then 2
                    else 3
                end,
                source_name  -- deterministic tiebreak inside a priority tier
        ) as source_rank
    from {{ source('raw', 'categories') }}
)

select
    category_name,
    category_value,
    source_name,
    source_version,
    product_type,
    device,
    start_ts_local,
    end_ts_local,
    hk_time_zone,
    hk_heart_rate_threshold,
    source_priority,
    source_file,
    source_sha256
from ranked
where source_rank = 1
