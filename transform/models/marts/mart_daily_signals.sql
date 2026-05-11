-- Wide-format daily signals for correlation / lagged analysis.
--
-- THIN selector on mart_recovery_state plus a numeric encoding of
-- recovery_signal. mart_recovery_state already joined RHR + HRV +
-- training-load with a date spine — re-joining the source marts here
-- would duplicate that work. So this mart selects, renames, and adds a
-- single numeric column. Lag/lead calculations live in the consumer
-- (Streamlit) so the mart stays raw.
--
-- recovery_score is a one-shot numeric mapping for correlation use:
--   well_recovered → 1, neutral → 0, strained → -1, insufficient_data → null.
--
-- Sleep duration is intentionally NOT here yet:
-- ingest/loaders/categories.py is unimplemented and no mart_daily_sleep
-- exists. Append a sleep_minutes column once that lands.

select
    day,
    rhr_bpm,
    hrv_ms,
    training_load_today as trimp,
    acwr,
    recovery_signal,
    case recovery_signal
        when 'well_recovered' then 1
        when 'neutral' then 0
        when 'strained' then -1
    end as recovery_score
from {{ ref('mart_recovery_state') }}
order by day
