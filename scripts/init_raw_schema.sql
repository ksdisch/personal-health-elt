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
    'SHA256 ledger of Health Auto Export CSVs already consumed. Loaders skip any file whose hash is present.';
