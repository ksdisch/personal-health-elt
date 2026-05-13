-- Initializes the raw schema and the file_inventory idempotency ledger.
-- Re-runnable: every statement is IF NOT EXISTS.
--
-- Loaders assume `raw` and `raw.file_inventory` exist. Source tables
-- (raw.quantities, raw.categories, raw.workouts) are created by their
-- respective loaders on first run so their columns stay colocated with
-- the loading code.
--
-- Apply via:
--   docker exec -i health_postgres psql -U health -d health \
--     < scripts/init_raw_schema.sql

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.file_inventory (
    sha256      TEXT PRIMARY KEY,
    file_name   TEXT NOT NULL,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE raw.file_inventory IS
    'SHA256 ledger of Apple Health CSVs already consumed. Loaders skip any file whose hash is present.';

-- Quantity metrics: HR, HRV, RHR, weight, sleep duration, VO2 max, energy, steps, ...
-- One row per HealthKit sample. Natural key: (metric_type, source_name, start_ts).
CREATE TABLE IF NOT EXISTS raw.quantities (
    metric_type    TEXT NOT NULL,
    source_name    TEXT,
    source_version TEXT,
    product_type   TEXT,
    device         TEXT,
    start_ts       TIMESTAMPTZ NOT NULL,
    end_ts         TIMESTAMPTZ,
    unit           TEXT,
    value          DOUBLE PRECISION NOT NULL,
    source_file    TEXT NOT NULL,
    source_sha256  TEXT NOT NULL REFERENCES raw.file_inventory(sha256),
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (metric_type, source_name, start_ts)
);

CREATE INDEX IF NOT EXISTS quantities_metric_time_idx
    ON raw.quantities (metric_type, start_ts);

COMMENT ON TABLE raw.quantities IS
    'Raw HealthKit quantity samples. Loaders upsert via ON CONFLICT on the natural key.';

-- Workouts: one row per HealthKit workout (run, ride, lift, yoga, ...).
-- Natural key: (activity_type, source_name, start_ts). Unit-embedded
-- source fields like "659.283 kcal" are parsed to numeric at the loader.
CREATE TABLE IF NOT EXISTS raw.workouts (
    activity_type     TEXT NOT NULL,
    source_name       TEXT,
    source_version    TEXT,
    product_type      TEXT,
    start_ts          TIMESTAMPTZ NOT NULL,
    end_ts            TIMESTAMPTZ NOT NULL,
    duration_sec      DOUBLE PRECISION NOT NULL,
    total_energy_kcal DOUBLE PRECISION,
    total_distance_m  DOUBLE PRECISION,
    elevation_asc_m   DOUBLE PRECISION,
    elevation_desc_m  DOUBLE PRECISION,
    max_speed_mps     DOUBLE PRECISION,
    indoor            BOOLEAN,
    source_file       TEXT NOT NULL,
    source_sha256     TEXT NOT NULL REFERENCES raw.file_inventory(sha256),
    loaded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (activity_type, source_name, start_ts)
);

CREATE INDEX IF NOT EXISTS workouts_activity_time_idx
    ON raw.workouts (activity_type, start_ts);
CREATE INDEX IF NOT EXISTS workouts_time_range_idx
    ON raw.workouts (start_ts, end_ts);

COMMENT ON TABLE raw.workouts IS
    'Raw HealthKit workouts. The time-range index supports the HR-sample join in intermediate models.';

-- Categories: HKCategoryTypeIdentifier* events (sleep stages, mindful
-- sessions, audio events, AppleStandHour, HR threshold events). Optional
-- per-type metadata (HKTimeZone on sleep rows, HKHeartRateEventThreshold
-- on HR events) lands in nullable TEXT columns.
-- Natural key: (category_type, source_name, start_ts).
CREATE TABLE IF NOT EXISTS raw.categories (
    category_type           TEXT NOT NULL,
    category_value          TEXT,
    source_name             TEXT,
    source_version          TEXT,
    product_type            TEXT,
    device                  TEXT,
    start_ts                TIMESTAMPTZ NOT NULL,
    end_ts                  TIMESTAMPTZ,
    hk_time_zone            TEXT,
    hk_heart_rate_threshold TEXT,
    source_file             TEXT NOT NULL,
    source_sha256           TEXT NOT NULL REFERENCES raw.file_inventory(sha256),
    loaded_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (category_type, source_name, start_ts)
);

CREATE INDEX IF NOT EXISTS categories_type_time_idx
    ON raw.categories (category_type, start_ts);

COMMENT ON TABLE raw.categories IS
    'Raw HealthKit category samples. Loaders upsert via ON CONFLICT on the natural key.';

-- Cross-source enrichment: daily weather summaries from OpenWeather
-- One Call 3.0 day_summary endpoint. Optional source — populated only
-- when OPENWEATHER_API_KEY + OPENWEATHER_LAT/LON are configured. Units
-- match the API's "standard" units: temperatures in Kelvin, wind in
-- m/s, pressure in hPa, precipitation in mm. Conversion happens at the
-- staging layer. PK on (obs_date, lat, lon) so re-running the loader
-- over an already-fetched range inserts zero rows.
CREATE TABLE IF NOT EXISTS raw.weather (
    obs_date              DATE NOT NULL,
    lat                   DOUBLE PRECISION NOT NULL,
    lon                   DOUBLE PRECISION NOT NULL,
    temp_min_k            DOUBLE PRECISION,
    temp_max_k            DOUBLE PRECISION,
    temp_morning_k        DOUBLE PRECISION,
    temp_afternoon_k      DOUBLE PRECISION,
    temp_evening_k        DOUBLE PRECISION,
    temp_night_k          DOUBLE PRECISION,
    humidity_afternoon    DOUBLE PRECISION,
    cloud_cover_afternoon DOUBLE PRECISION,
    pressure_afternoon    DOUBLE PRECISION,
    precip_total_mm       DOUBLE PRECISION,
    wind_max_mps          DOUBLE PRECISION,
    wind_max_dir_deg      DOUBLE PRECISION,
    loaded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (obs_date, lat, lon)
);

CREATE INDEX IF NOT EXISTS weather_date_idx ON raw.weather (obs_date);

COMMENT ON TABLE raw.weather IS
    'Daily weather summaries from OpenWeather One Call 3.0. Units are the API''s "standard" (K / m/s / hPa / mm). Conversion to C / mph / etc. happens in stg_weather.';

-- Cross-source enrichment: daily Google Calendar density aggregates.
-- One row per (day, source_sha256). Populated by the calendar loader,
-- which fetches the user's secret iCal URL once per flow, expands
-- recurring events into instances, and rolls up into per-day counts +
-- hours. File-level idempotency uses raw.file_inventory (SHA256 of the
-- ICS response body), so an unchanged calendar short-circuits at the
-- ledger check. When the ICS body changes (events added / removed),
-- a new SHA produces a new set of (day, sha) rows; stg_calendar takes
-- the latest SHA per day so the mart sees the freshest view.
CREATE TABLE IF NOT EXISTS raw.calendar_daily (
    day                  DATE NOT NULL,
    timed_event_count    INTEGER NOT NULL DEFAULT 0,
    timed_event_hours    DOUBLE PRECISION NOT NULL DEFAULT 0,
    all_day_event_count  INTEGER NOT NULL DEFAULT 0,
    first_event_local    TIMESTAMP,
    last_event_local     TIMESTAMP,
    source_sha256        TEXT NOT NULL REFERENCES raw.file_inventory(sha256),
    loaded_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (day, source_sha256)
);

CREATE INDEX IF NOT EXISTS calendar_daily_day_idx ON raw.calendar_daily (day);

COMMENT ON TABLE raw.calendar_daily IS
    'Per-day calendar density (timed event count / hours / first / last) parsed from a Google Calendar secret iCal URL. Recurring events expanded into instances before aggregation.';
