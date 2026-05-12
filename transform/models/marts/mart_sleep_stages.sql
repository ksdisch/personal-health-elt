-- Hypnogram data source: one row per sleep-stage segment per night.
--
-- Renames the intermediate's start/end columns to stage_start_local /
-- stage_end_local for clarity downstream, and adds stage_seq_in_night so
-- ordered rendering (Streamlit hypnogram) doesn't have to sort on its own.
--
-- One row per (night_date, stage_start_local). Enforced by the
-- compound-unique singular test in transform/tests/.

with segments as (
    select
        night_date,
        start_ts_local as stage_start_local,
        end_ts_local   as stage_end_local,
        duration_min,
        sleep_stage,
        is_asleep,
        source_name,
        row_number() over (
            partition by night_date
            order by start_ts_local
        ) as stage_seq_in_night
    from {{ ref('int_sleep_segments') }}
)

select
    night_date,
    stage_start_local,
    stage_end_local,
    round(duration_min::numeric, 1)::double precision as duration_min,
    sleep_stage,
    is_asleep,
    source_name,
    stage_seq_in_night
from segments
order by night_date, stage_start_local
