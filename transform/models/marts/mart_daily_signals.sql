-- Wide-format daily signals for correlation / lagged analysis.
--
-- THIN selector on mart_recovery_state plus a numeric encoding of
-- recovery_signal. mart_recovery_state already joined RHR + HRV +
-- training-load with a date spine — re-joining the source marts here
-- would duplicate that work. So this mart selects, renames, and adds a
-- single numeric column. Lag/lead calculations live in the consumer
-- (Streamlit) so the mart stays raw.
--
-- Companion of mart_recovery_state: same daily grain and overlapping
-- columns. mart_recovery_state is the public-API contract for the
-- weekly-health-review skill; this mart is the internal correlation lens.
--
-- recovery_score is a one-shot numeric mapping for correlation use:
--   well_recovered → 1, neutral → 0, strained → -1, insufficient_data → null.

select
    rs.day,
    rs.rhr_bpm,
    rs.hrv_ms,
    rs.training_load_today as trimp,
    rs.acwr,
    rs.recovery_signal,
    case rs.recovery_signal
        when 'well_recovered' then 1
        when 'neutral' then 0
        when 'strained' then -1
    end as recovery_score,
    sn.time_asleep_min as sleep_minutes
from {{ ref('mart_recovery_state') }} rs
left join {{ ref('mart_sleep_nights') }} sn on sn.night_date = rs.day
order by rs.day
