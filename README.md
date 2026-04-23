# personal-health-elt

A personal Apple Health ELT pipeline. CSV exports from the
[Health Auto Export](https://www.healthyapps.dev/) iOS app land on disk, get loaded
into Postgres, transformed with dbt into analytics-ready marts, and visualized in
a Streamlit app. The final mart (`mart_recovery_state`) is the input for an
external Claude skill called `weekly-health-review`, which in turn feeds
`weekly-workout-planner`.

## Architecture

```
┌─────────────────────┐     ┌──────────────┐     ┌────────────────┐     ┌──────────────┐
│ Health Auto Export  │     │   ingest/    │     │   Postgres 16  │     │  transform/  │
│ (iOS app → CSV)     │ ──► │  (Python +   │ ──► │                │ ──► │   (dbt)      │
│ 87 metric types     │     │   Prefect)   │     │  raw schema    │     │              │
└─────────────────────┘     └──────────────┘     └────────────────┘     └──────┬───────┘
                                                                               │
                                              ┌────────────────────────────────┤
                                              │                                │
                                              ▼                                ▼
                                      ┌──────────────┐              ┌──────────────────┐
                                      │  Streamlit   │              │ mart_recovery_   │
                                      │     app/     │              │ state (public)   │
                                      └──────────────┘              └────────┬─────────┘
                                                                             │
                                                                             ▼
                                                               ┌──────────────────────┐
                                                               │ weekly-health-review │
                                                               │   Claude skill       │
                                                               └──────────┬───────────┘
                                                                          │
                                                                          ▼
                                                               ┌──────────────────────┐
                                                               │ weekly-workout-      │
                                                               │   planner            │
                                                               └──────────────────────┘
```

## Stack

| Layer          | Tool                              |
| -------------- | --------------------------------- |
| Language       | Python 3.12 (managed by `uv`)     |
| Database       | Postgres 16 (Docker)              |
| Orchestration  | Prefect 3.x                       |
| Transforms     | dbt-core + dbt-postgres           |
| Visualization  | Streamlit                         |
| Lint / Test    | Ruff, pytest, mypy                |
| CI             | GitHub Actions                    |

## Roadmap

**Week 1 — Foundations.** Postgres running locally; file inventory with
hash-based dedup; loaders wired end-to-end for one metric; first dbt staging
model; first Streamlit chart.

**Week 2 — Breadth.** Generic quantities loader covering ~15–20 priority
metrics (resting HR, HRV, weight, sleep, VO2 max, active/basal energy, steps).

**Week 3 — Workouts + Integration.** Workouts loader; range-based joins
(HR samples × workout windows); `mart_training_load` (weekly Zone 2 minutes,
ACWR, strength volume); `mart_recovery_state`.

**Week 4 — Automation + Skill Integration.** Prefect scheduled flow; wire
`weekly-health-review` Claude skill to `mart_recovery_state`; README polish
for portfolio presentation.

## Local setup

```bash
# 1. Start Postgres + pgAdmin (pgAdmin on localhost:5050)
docker compose up -d

# 2. Wire credentials
cp .env.example .env
cp transform/profiles.yml.example transform/profiles.yml

# 3. Install deps
uv sync

# 4. Create the raw schema + file_inventory table
docker exec -i health_postgres psql -U health -d health \
  < scripts/init_raw_schema.sql

# 5. Verify dbt ↔ Postgres
uv run dbt debug --project-dir transform --profiles-dir transform

# 6. Load HR zones seed
uv run dbt seed --project-dir transform --profiles-dir transform

# 7. Run the Streamlit app
uv run streamlit run app/home.py
```

## Portfolio notes

A few deliberate design choices worth calling out:

- **Idempotent loaders.** Apple re-exports contain full history. Loaders key on
  a hash of the row (or natural key) so re-running a load is safe — no
  duplicates, no partial writes.
- **Strict dbt layering.** `staging → intermediate → marts`, no shortcuts.
  Staging does 1:1 source reflection plus timezone normalization (everything
  lands in `America/Chicago`). Intermediate holds business-logic joins.
  Marts are the only layer downstream consumers see.
- **Multi-source dedup priority.** When the same metric comes from multiple
  devices (Apple Watch, iPhone, third-party apps), staging picks the winner by
  a fixed priority: `Apple Watch > iPhone > third-party`.
- **Public mart = public API.** `mart_recovery_state` feeds an external Claude
  skill. Schema changes there require updating the skill in lockstep — so the
  mart is treated like a versioned interface, not an implementation detail.
- **HR zones are config, not code.** My Zone 2 boundaries live in
  `transform/seeds/hr_zones.csv`, not hardcoded in SQL. Easy to tune without
  a code change.
- **CI green from day one.** `ruff check`, `pytest`, and `dbt parse` all run
  on every push so nothing drifts.
