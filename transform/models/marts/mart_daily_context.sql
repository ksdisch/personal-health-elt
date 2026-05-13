-- Daily external-context mart. Grain: one row per calendar day in any
-- enrichment source (weather or calendar). Downstream correlation
-- analysis joins this to mart_recovery_state on `day`.
--
-- Currently joins weather + calendar density. Future loaders (Oura
-- ring temp, HomeKit) plug in as additional left joins on the same
-- day spine. As long as the spine covers every day either source has
-- touched, growth is additive — no breaking changes for consumers.
--
-- Deliberately a SEPARATE mart from mart_recovery_state. The latter
-- is the public API consumed by the weekly-health-review Claude
-- skill; mixing external columns into it would broaden that
-- contract. Page 09 (correlations) joins the two marts on `day`.

with day_spine as (
    -- Union the day columns from every enrichment source. Each source
    -- is optional (empty when its env var is unset), so the spine is
    -- itself optional — an empty spine means the entire mart is empty
    -- (loaders are no-ops, page 09 shows the info card). Intended.
    select day from {{ ref('stg_weather') }}
    union
    select day from {{ ref('stg_calendar') }}
)

select
    s.day,

    -- Weather columns ----------------------------------------------------
    w.temp_min_c,
    w.temp_max_c,
    w.temp_afternoon_c,
    w.temp_night_c,
    w.humidity_afternoon,
    w.cloud_cover_afternoon,
    w.precip_total_mm,
    w.wind_max_mps,

    -- Calendar density columns ------------------------------------------
    coalesce(c.timed_event_count, 0)   as timed_event_count,
    coalesce(c.timed_event_hours, 0.0) as timed_event_hours,
    coalesce(c.all_day_event_count, 0) as all_day_event_count,
    c.first_event_local,
    c.last_event_local
from day_spine s
left join {{ ref('stg_weather') }}  w on w.day = s.day
left join {{ ref('stg_calendar') }} c on c.day = s.day
order by s.day
