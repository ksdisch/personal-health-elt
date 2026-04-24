-- Daily body mass (kg) in America/Chicago. One row per day. If a scale
-- logs multiple readings on the same day, keep the last one (most recent
-- reading is generally what the user cares about).
--
-- Currently empty for Kyle — no smart scale in use. The unique(day) test
-- guards the "one row per day" contract once data starts flowing.

with ranked as (
    select
        start_ts_local::date as day,
        value                as weight_kg,
        source_name,
        unit,
        row_number() over (
            partition by start_ts_local::date
            order by start_ts_local desc
        ) as rn
    from {{ ref('stg_quantities') }}
    where metric_name = 'BodyMass'
)

select day, weight_kg, source_name, unit
from ranked
where rn = 1
order by day
