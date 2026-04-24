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
