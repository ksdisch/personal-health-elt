-- Staging layer for raw.calendar_daily.
--
-- Responsibilities (and ONLY these):
--   1. Resolve the (day, source_sha256) grain down to one row per day
--      by picking the LATEST loaded SHA. When the user adds/removes
--      events the ICS body SHA changes and a fresh row-set is inserted
--      under a new SHA; the older SHA's rows linger in raw but should
--      not be served downstream.
--   2. Pass through the density columns unchanged. Timestamps already
--      live in local civil time (the loader converts on parse).
--
-- No business logic here. mart_daily_context handles the join + any
-- derived metrics ("busy hours / standard work hours" etc).

with ranked as (
    select
        day,
        timed_event_count,
        timed_event_hours,
        all_day_event_count,
        first_event_local,
        last_event_local,
        source_sha256,
        loaded_at,
        row_number() over (
            partition by day
            order by loaded_at desc, source_sha256
        ) as sha_rank
    from {{ source('raw', 'calendar_daily') }}
)

select
    day,
    timed_event_count,
    timed_event_hours,
    all_day_event_count,
    first_event_local,
    last_event_local
from ranked
where sha_rank = 1
