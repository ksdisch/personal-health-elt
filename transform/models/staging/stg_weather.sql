-- Staging layer for raw.weather.
--
-- Responsibilities (and ONLY these):
--   1. Convert temperatures from Kelvin (OpenWeather "standard" units)
--      to Celsius.
--   2. Pass through everything else as-is. obs_date is already local to
--      the configured (lat, lon) per the day_summary endpoint contract
--      — no further timezone conversion needed.
--
-- No business logic here. Joins to other daily marts happen in
-- mart_daily_context.

select
    obs_date                          as day,
    lat,
    lon,
    temp_min_k       - 273.15         as temp_min_c,
    temp_max_k       - 273.15         as temp_max_c,
    temp_morning_k   - 273.15         as temp_morning_c,
    temp_afternoon_k - 273.15         as temp_afternoon_c,
    temp_evening_k   - 273.15         as temp_evening_c,
    temp_night_k     - 273.15         as temp_night_c,
    humidity_afternoon,
    cloud_cover_afternoon,
    pressure_afternoon                as pressure_hpa_afternoon,
    precip_total_mm,
    wind_max_mps,
    wind_max_dir_deg
from {{ source('raw', 'weather') }}
