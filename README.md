# personal-health-elt

[![CI](https://github.com/ksdisch/personal-health-elt/actions/workflows/ci.yml/badge.svg)](https://github.com/ksdisch/personal-health-elt/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![dbt 1.11](https://img.shields.io/badge/dbt-1.11-orange.svg)](https://docs.getdbt.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A personal Apple Health ELT pipeline, end to end. CSV exports from a
HealthKit-compatible iOS app land on disk, get loaded into Postgres,
transformed with dbt into analytics-ready marts, and visualized in a
Streamlit app. The final mart (`mart_recovery_state`) is a public API
consumed by an external Claude skill called `weekly-health-review`,
which feeds `weekly-workout-planner`.

This is also a **portfolio project for Analytics Engineer / Data
Engineer roles**, so code quality, dbt conventions, and design choices
are part of the deliverable.

## Live app

_TODO: paste the deployed Streamlit URL here once the cloud deploy
lands. The full step-by-step is in_ [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
_— it covers managed Postgres provisioning (Supabase / Neon / Railway),
secrets, cold-start ingest, three deploy targets (Streamlit Cloud /
Fly / Railway), and the redeploy path._

## What this demonstrates

| Skill area | In this repo |
| --- | --- |
| **Idempotent ingestion** | SHA256 file ledger + ON CONFLICT row-level dedup, in one transaction. Re-running any loader is safe. |
| **Range-based SQL** | `int_workout_hr_samples` joins HR samples to workout windows; LEAD() computes per-sample duration; materialized as table to amortize the cost. |
| **dbt layering** | Strict `staging → intermediate → marts`. Marts never select from `source()`. Layer-level tests on every model. |
| **Public-API contract** | `mart_recovery_state` schema is enforced via dbt `accepted_values` + `unique` tests. The downstream skill consumes it. |
| **Multi-source dedup** | Apple Watch > iPhone > third-party — encoded as a `source_priority` window function in staging. |
| **Time correctness** | UTC at rest, `America/Chicago` everywhere downstream. TZ conversion lives in exactly one layer. |
| **Date-spine rolling windows** | `mart_training_load` generates a contiguous date series so 7-day / 28-day rolling averages denominate correctly through zero-load days. |
| **Real Streamlit UX** | 4 pages including a Weekly Review with Altair-rendered ACWR chart on color-coded sweet-spot / injury-risk bands. |
| **Closed-loop integration** | dbt mart → Python briefing generator → vault Markdown → consumer skill — all idempotent and recoverable. |

**Scale of real data flowing through right now:** 286,770 quantity samples across 35 metric types · 78 workouts · 30,859 HR samples joined to workout windows · 31 daily recovery-state rows · all loaded in ~10 seconds end-to-end.

## Screenshots

### Weekly Review — `mart_recovery_state` consumer surface

The headline page. Recovery signal as a colored badge, ACWR trajectory on green sweet-spot / red injury-risk bands, HRV vs. 7-day prior baseline, and the last 14 days as a sortable table. The "What the skill sees" expander at the bottom shows the exact JSON payload that goes to the `weekly-health-review` Claude skill.

![Weekly Review page](docs/screenshots/weekly_review.png)

### Training Load — the SQL interesting bits made visual

Acute (7d) vs. chronic (28d) load lines, rolling Zone 2 minutes, and a per-workout zone-stack chart colored by intensity (Zone 1 grey → Zone 5 red). Each bar is one workout's actual time-in-zone, computed from the `int_workout_hr_samples` range-join.

![Training Load page](docs/screenshots/training_load.png)

### Daily — per-metric tabs

Resting HR, HRV, VO₂ Max, and Weight tabs with a shared 3-card-and-trend layout. The Weight tab shows an empty-state hint (no smart scale data yet — the `mart_daily_weight` mart is shipped and waiting).

![Daily page](docs/screenshots/daily.png)

## Architecture

```
                              ┌───────────────────────┐
                              │  HealthKit CSV export │
                              │  (iOS → data/raw/)    │
                              └──────────┬────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
           ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
           │   quantities    │  │    workouts     │  │   categories    │
           │     loader      │  │     loader      │  │   (TODO Wk5)    │
           └────────┬────────┘  └────────┬────────┘  └─────────────────┘
                    │                    │              SHA256 file ledger
                    └─────────┬──────────┘              + ON CONFLICT dedup
                              ▼
                    ┌─────────────────────┐
                    │  Postgres 16 (raw)  │  raw.quantities, raw.workouts,
                    └──────────┬──────────┘  raw.file_inventory
                               │
                               ▼  dbt (staging → intermediate → marts)
                    ┌─────────────────────┐
                    │ stg_quantities      │  TZ → America/Chicago,
                    │ stg_workouts        │  source-priority dedup
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ int_workout_hr_     │  range-join, LEAD() durations,
                    │   samples           │  zone lookup. (table-materialized)
                    └──────────┬──────────┘
                               │
            ┌──────────────────┼──────────────────────┐
            ▼                  ▼                      ▼
   ┌────────────────┐  ┌────────────────┐    ┌────────────────┐
   │ mart_daily_*   │  │ mart_workout_  │    │ mart_training_ │
   │ (rhr/hrv/      │  │   zones        │    │  load (TRIMP   │
   │  vo2max/wt)    │  │                │    │  + ACWR)       │
   └────────┬───────┘  └────────┬───────┘    └────────┬───────┘
            │                   │                     │
            └───────────────────┼─────────────────────┘
                                ▼
                    ┌─────────────────────┐
                    │ mart_recovery_state │  ★ PUBLIC API
                    │ (one row per day)   │  contract-tested
                    └──────┬──────┬───────┘
                           │      │
           ┌───────────────┘      └────────────────────┐
           ▼                                           ▼
   ┌────────────────┐                       ┌──────────────────────┐
   │ Streamlit app  │                       │ scripts/weekly_      │
   │ (4 pages,      │                       │  health_review.py    │
   │  Altair)       │                       │ (briefing → stdout)  │
   └────────────────┘                       └──────────┬───────────┘
                                                       │
                                                       ▼
                                       ┌──────────────────────────┐
                                       │ weekly-health-review     │
                                       │  Claude skill            │
                                       └──────────┬───────────────┘
                                                  │
                                                  ▼
                              vault: 40-areas/health/weekly-health-reviews.md
                                                  │
                                                  ▼
                                       ┌──────────────────────────┐
                                       │ weekly-workout-planner   │  reads latest H2,
                                       │  Claude skill            │  applies recovery
                                       └──────────────────────────┘  rules to next plan
```

Prefect schedules `weekly_load` on Sunday 11 AM CT to refresh raw + dbt.

## Stack

| Layer          | Tool                              |
| -------------- | --------------------------------- |
| Language       | Python 3.12 (managed by `uv`)     |
| Database       | Postgres 16 (Docker)              |
| Orchestration  | Prefect 3.x                       |
| Transforms     | dbt-core + dbt-postgres           |
| Visualization  | Streamlit + Altair                |
| Lint / Test    | Ruff, pytest, mypy                |
| CI             | GitHub Actions (ruff + dbt parse + pytest) |

## Roadmap

**Week 1 — Foundations.** ✅ Postgres up, idempotent file inventory, RestingHeartRate loaded end-to-end, first staging model + mart, first Streamlit chart.

**Week 2 — Breadth.** ✅ Generic quantities loader (35 metric types: HR, HRV, RHR, VO2 Max, energy, steps, dietary, ...). Batch dispatcher walks a folder and routes each CSV by HK type prefix.

**Week 3 — Workouts + Integration.** ✅ Workouts loader (unit-embedded value parser), `int_workout_hr_samples` (range-joined, zone-tagged), `mart_workout_zones`, `mart_training_load` (TRIMP + ACWR), `mart_recovery_state` (public API).

**Week 4 — Automation + Skill Integration.** ✅ Prefect scheduled flow (Sunday 11 AM CT). `weekly-health-review` Claude skill reads `mart_recovery_state`, writes a vault briefing. `weekly-workout-planner` skill reads the briefing and adjusts its plan (deload on injury-risk ACWR, rebuild volume on under-training, sacred Mon Yoga / Sun Rest preserved).

**What's deferred.** `categories` loader (sleep stages, mindfulness sessions). Rich derived marts on dietary metrics. Prefect scheduler running under launchd for survive-sleep durability. dbt source freshness checks.

## Local setup

```bash
# 1. Start Postgres + pgAdmin (pgAdmin on localhost:5050)
docker compose up -d

# 2. Wire credentials
cp .env.example .env
cp transform/profiles.yml.example transform/profiles.yml

# 3. Install deps
uv sync

# 4. Create the raw schema
docker exec -i health_postgres psql -U health -d health \
  < scripts/init_raw_schema.sql

# 5. Verify dbt ↔ Postgres
uv run dbt debug --project-dir transform --profiles-dir transform

# 6. Load HR zones seed
uv run dbt seed --project-dir transform --profiles-dir transform

# 7. Drop your HealthKit-export CSVs into data/raw/, then load them all
uv run python -m ingest.loaders.batch data/raw/

# 8. Build the marts
uv run dbt build --project-dir transform --profiles-dir transform

# 9. Run the Streamlit app
uv run streamlit run app/home.py
```

## Pre-commit hooks (optional but recommended)

Local gates that mirror CI — catch lint / format / type errors before
they hit a branch. One-time install:

```bash
uv tool install pre-commit
pre-commit install --hook-type pre-commit --hook-type pre-push
```

After install, `git commit` runs `ruff check` + `ruff format --check`
and `git push` adds `mypy ingest` (slower, so push-only). Configuration
lives in `.pre-commit-config.yaml` at repo root.

To run the hooks manually against all files:

```bash
pre-commit run --all-files          # pre-commit hooks (fast)
pre-commit run --hook-stage pre-push --all-files
```

## Scheduled refresh (optional)

The Prefect flow `ingest.flows.weekly_load` walks `data/raw/`, loads any
new HK CSVs through the batch dispatcher, and triggers `dbt build` if rows
landed. It's idempotent — re-running on a clean folder is a no-op.

```bash
# Run once:
uv run python -m ingest.flows.weekly_load

# Long-lived scheduler (Sunday 11 AM CT):
uv run python -m ingest.flows.weekly_load --serve
```

`--serve` registers a cron schedule and stays running. Pair it with `caffeinate`
or a launchd plist if you want it to survive sleep.

## Generate the weekly briefing

Once data is loaded, produce the markdown block consumed by the
`weekly-health-review` skill:

```bash
uv run python scripts/weekly_health_review.py
```

Pipes a complete H2 block to stdout — signal headline, day-by-day table,
1–4 prescriptive recommendations derived from real rules (ACWR sweet spot,
HRV trend, Zone 2 deficit, strain-day count).

## Common commands

A cheat sheet for day-to-day operation. All commands run from the project root.

```bash
# Daily ops
uv run python -m ingest.loaders.batch data/raw/      # load any new HK CSVs (idempotent)
uv run dbt build --project-dir transform --profiles-dir transform   # rebuild marts + run all tests
uv run python scripts/weekly_health_review.py        # generate this week's briefing markdown
uv run streamlit run app/home.py                     # serve the dashboard

# Verification (instant, run any time)
uv run ruff check .                                  # lint
uv run pytest                                        # unit tests (37, ~0.5s)
uv run dbt parse  --project-dir transform --profiles-dir transform  # dbt syntax check
uv run dbt debug  --project-dir transform --profiles-dir transform  # connection test
docker compose ps                                    # are the containers up?

# DB introspection
docker exec -i health_postgres psql -U health -d health   # interactive psql
docker exec -i health_postgres psql -U health -d health -c "\
  SELECT 'quantities' AS tbl, COUNT(*) FROM raw.quantities \
  UNION ALL SELECT 'workouts', COUNT(*) FROM raw.workouts \
  UNION ALL SELECT 'recovery', COUNT(*) FROM analytics_marts.mart_recovery_state;"
```

## Read the code

Direct links to the most interesting files, in case you're skimming:

- [`transform/models/marts/mart_recovery_state.sql`](transform/models/marts/mart_recovery_state.sql) — the public-API mart. Contract-tested with `accepted_values` on `recovery_signal` and `unique(day)`.
- [`transform/models/intermediate/int_workout_hr_samples.sql`](transform/models/intermediate/int_workout_hr_samples.sql) — the range-join (workouts × HR samples) plus `LEAD()` per-sample duration. Materialized as a table to amortize cost.
- [`transform/models/marts/mart_training_load.sql`](transform/models/marts/mart_training_load.sql) — date-spine + rolling 7-day acute / 28-day chronic + ACWR. The denominate-correctly-through-rest-days move.
- [`transform/models/staging/stg_quantities.sql`](transform/models/staging/stg_quantities.sql) — TZ normalization + multi-source dedup (Apple Watch > iPhone > other) via `row_number()`.
- [`ingest/loaders/quantities.py`](ingest/loaders/quantities.py) — two-level idempotency: SHA file ledger + ON CONFLICT row dedup, both inside `engine.begin()`.
- [`ingest/loaders/workouts.py`](ingest/loaders/workouts.py) — unit-embedded value parser (`"659.283 kcal"` → `659.283`), tolerant of missing columns per activity type.
- [`scripts/weekly_health_review.py`](scripts/weekly_health_review.py) — briefing generator. Rule-based recommendations (ACWR sweet-spot, HRV trend, Z2 deficit, strain count).
- [`app/pages/02_weekly_review.py`](app/pages/02_weekly_review.py) — the Streamlit page screenshotted above. Altair layered chart with `mark_rect` bands.
- [`transform/seeds/hr_zones.csv`](transform/seeds/hr_zones.csv) — HR zones as configuration. Zone 2 locked at 136–153 bpm.

## Project structure

```
personal-health-elt/
├── ingest/                  Python — config, file inventory, loaders, Prefect flow
│   ├── loaders/
│   │   ├── quantities.py    handles 35 HK quantity metric types
│   │   ├── workouts.py      handles HK workouts (unit-embedded values)
│   │   └── batch.py         dispatch table + folder walker
│   └── flows/weekly_load.py Prefect flow + cron schedule
├── transform/               dbt project
│   ├── models/
│   │   ├── staging/         stg_quantities, stg_workouts (TZ + source-priority)
│   │   ├── intermediate/    int_workout_hr_samples (range-join, table-materialized)
│   │   └── marts/           mart_daily_* + mart_workout_zones + mart_training_load + mart_recovery_state★
│   ├── seeds/hr_zones.csv   Zone 2 locked at 136–153 bpm (user's measured zone)
│   └── tests/               schema-level tests on every model
├── app/                     Streamlit (home + Daily + Weekly Review + Training Load)
├── scripts/
│   ├── init_raw_schema.sql  raw schema bootstrap
│   └── weekly_health_review.py  briefing generator (stdout → vault)
└── tests/                   pytest unit tests for loaders + parsers
```

## Portfolio notes

A few deliberate design choices worth calling out:

- **Idempotent loaders, two levels.** Apple re-exports contain full
  history. Loaders dedup at the file level (SHA256 ledger in
  `raw.file_inventory`) AND at the row level (`ON CONFLICT (metric_type,
  source_name, start_ts) DO NOTHING`). Both happen in one transaction —
  a failed insert rolls back the file_inventory record, so retry is
  clean. Real bug found and fixed: pandas `NaN` in object columns lands
  in Postgres TEXT as the literal string `"NaN"` unless coerced to
  `None` at the record boundary. Caught by running on real data, not
  by tests.

- **The interesting SQL.** `int_workout_hr_samples` cross-joins 78
  workouts × 43k HR samples, filters by time range, tags each sample
  with a zone via `BETWEEN` against the `hr_zones` seed, and uses
  `LEAD()` to compute per-sample duration (`coalesce(next_ts,
  workout_end_ts) - current_ts`). Originally a view; materialized as a
  table after profiling — the join is the biggest cost in the project,
  and every downstream mart + test re-executes it. Materialization
  drops downstream reads from seconds to microseconds.

- **Date-spine rolling averages.** `mart_training_load` `generate_series`'s
  the observed range so zero-load days count as 0, not "missing". 7-day
  acute and 28-day chronic averages denominate correctly through rest
  weeks. ACWR = acute/chronic; sweet spot 0.8–1.3, injury risk > 1.5.
  Foot-gun avoided by design.

- **`mart_recovery_state` as a versioned interface.** Schema enforced
  via dbt `accepted_values` (`recovery_signal IN ('well_recovered',
  'neutral', 'strained', 'insufficient_data')`) and `unique(day)`.
  Changes here require updating the consumer skill in lockstep — the
  test fails before the skill does.

- **Multi-source dedup priority.** When the same metric comes from
  multiple devices, staging picks the winner via `source_priority`:
  Apple Watch (1) > iPhone (2) > third-party (3). Encoded as a
  `row_number() OVER (PARTITION BY metric_type, start_ts ORDER BY
  source_priority)` in `stg_quantities`, filtered to rank 1.

- **Time correctness lives in exactly one place.** `start_ts` lands in
  the warehouse as UTC. Staging is the only layer that converts to
  `America/Chicago`. Intermediate and marts treat local time as
  authoritative. If anything downstream sees a UTC timestamp, that's
  a bug in staging — not a "fix it everywhere" panic.

- **HR zones are config, not code.** Zone 2 is locked to 136–153 bpm
  in `transform/seeds/hr_zones.csv` (the user's measured Zone 2). A
  workout-zones change requires a seed edit + `dbt seed`, not a SQL
  migration.

- **Rule-based recovery signal, not ML.** `mart_recovery_state.recovery_signal`
  is a 3-tier bucket from explicit rules (`acwr > 1.5 → strained`,
  `hrv < 0.85 × baseline → strained`, etc.). The bucket is a hint;
  raw inputs (`rhr_bpm`, `hrv_ms`, `acwr`, `days_since_last_workout`)
  are also exposed. The downstream skill can override the bucket but
  shouldn't have to recompute the inputs.

- **Closed-loop skill integration.** The full chain works:
  `Apple Watch → Postgres → mart_recovery_state → Python briefing
  generator → vault Markdown → weekly-health-review skill → second
  vault file → weekly-workout-planner skill → recovery-aware 7-day
  plan → morning briefing reads today's row`. Every step is
  idempotent and re-runnable.

- **CI green from day one.** `ruff check`, `pytest`, and
  `dbt parse` run on every push. Real-data integration tests are
  manual locally; CI stays hermetic.
