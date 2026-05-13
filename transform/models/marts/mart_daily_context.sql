-- Daily external-context mart — first cut of cross-source enrichment.
--
-- Grain: one row per calendar day. Joins external factors (today:
-- weather only) onto a date spine so downstream correlation analysis
-- can ask questions like:
--   "does my recovery score drop on hot nights?"
--   "do I sleep worse after rainy / low-pressure days?"
--   "is HRV correlated with overnight temp?"
--
-- Deliberately a SEPARATE mart from mart_recovery_state. The latter is
-- the public API consumed by the weekly-health-review Claude skill;
-- mixing external-source columns into it would broaden that contract.
-- Page 09 (correlations) and any other consumer joins the two marts on
-- `day` rather than reading them as one.
--
-- As calendar / Oura / HomeKit loaders land, additional left joins (or
-- tall-format unions) plug in here. The mart_daily_context contract is
-- "everything downstream of staging that describes external context
-- for the day."

select
    day,
    temp_min_c,
    temp_max_c,
    temp_afternoon_c,
    temp_night_c,
    humidity_afternoon,
    cloud_cover_afternoon,
    precip_total_mm,
    wind_max_mps
from {{ ref('stg_weather') }}
order by day
