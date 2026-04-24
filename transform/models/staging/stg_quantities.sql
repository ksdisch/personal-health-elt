-- Staging layer for raw.quantities.
--
-- Responsibilities (and ONLY these):
--   1. Strip the HK*TypeIdentifier prefix from metric_type → metric_name.
--   2. Convert UTC timestamps to America/Chicago.
--   3. Tag each row with a source_priority and keep only the winning source
--      per (metric_name, start_ts_local). Per CLAUDE.md:
--        Apple Watch > iPhone > everything else.
--
-- No business logic lives here — that's intermediate/marts.

with ranked as (
    select
        regexp_replace(metric_type, '^HK(Quantity|Category)TypeIdentifier', '') as metric_name,
        source_name,
        source_version,
        product_type,
        device,
        (start_ts at time zone 'America/Chicago')::timestamp as start_ts_local,
        (end_ts   at time zone 'America/Chicago')::timestamp as end_ts_local,
        unit,
        value,
        case
            when source_name ilike '%apple watch%' then 1
            when source_name ilike '%iphone%'      then 2
            else 3
        end as source_priority,
        source_file,
        source_sha256,
        row_number() over (
            partition by metric_type, start_ts
            order by
                case
                    when source_name ilike '%apple watch%' then 1
                    when source_name ilike '%iphone%'      then 2
                    else 3
                end,
                source_name  -- deterministic tiebreak inside a priority tier
        ) as source_rank
    from {{ source('raw', 'quantities') }}
)

select
    metric_name,
    source_name,
    source_version,
    product_type,
    device,
    start_ts_local,
    end_ts_local,
    unit,
    value,
    source_priority,
    source_file,
    source_sha256
from ranked
where source_rank = 1
