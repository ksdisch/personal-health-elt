# CLAUDE.md — context bridge for `personal-health-elt`

This file is the durable context that any Claude Code session should read before
touching this project. It captures decisions that aren't obvious from the code
alone.

## What this project is

A personal Apple Health ELT pipeline. Health Auto Export writes CSVs; Python
loaders land them in Postgres `raw`; dbt transforms them into marts; Streamlit
visualizes them. The mart `mart_recovery_state` is consumed by an external
Claude skill called `weekly-health-review`, which in turn feeds
`weekly-workout-planner`.

This is also a portfolio project for Analytics Engineer / Data Engineer roles,
so code quality, README polish, and dbt conventions are part of the product.

## Stack

- Python 3.12, managed with `uv` (never `pip install` directly — always
  `uv add` / `uv sync` / `uv run`)
- Postgres 16 in Docker (see `docker-compose.yml`)
- Prefect 3.x (uses `@flow` / `@task` decorators — not the legacy 2.x API)
- dbt-core + dbt-postgres
- Streamlit for the app
- Ruff for lint, pytest for tests, mypy for optional typing
- GitHub Actions for CI

## Directory map

- `ingest/` — Python package. Config, file inventory, loaders (quantities,
  categories, workouts), Prefect flows.
- `transform/` — dbt project root. Staging / intermediate / marts models,
  seeds, tests, macros.
- `app/` — Streamlit app. `home.py` + numbered pages under `pages/`.
- `tests/` — pytest unit tests (separate from dbt tests, which live under
  `transform/tests/`).
- `data/raw/` — Health Auto Export drop folder. Gitignored.
- `.github/workflows/ci.yml` — ruff + pytest + dbt parse.

## Non-negotiable conventions

### Loaders MUST be idempotent
Apple re-exports contain full history. Every loader dedups on either a hash
of the row or a natural key (`metric_name + source + start_ts`). Re-running a
load on the same file MUST be a no-op — no duplicates, no partial writes.

### Timezones normalized at staging
All timestamps land in the warehouse as UTC and are converted to
`America/Chicago` at the staging layer. Never normalize TZ in intermediate
or marts — staging owns that step.

### Multi-source dedup priority
When the same metric appears from multiple devices, pick the winner in this
order: **Apple Watch > iPhone > third-party apps**. This lives in staging as
a window function (`row_number() over (partition by metric, ts order by
source_priority)`).

### dbt layering is strict
`staging → intermediate → marts`. No shortcuts. Marts MUST NOT select from
`source()` directly. Intermediate MUST NOT be the final consumer of source data.

Materializations by layer (defaults in `dbt_project.yml`):
- staging: view
- intermediate: view
- marts: table

### `mart_recovery_state` is a public API
The `weekly-health-review` Claude skill consumes this mart. Schema changes
(renaming a column, dropping a field, changing a unit) require updating that
skill in lockstep. Treat the mart like a versioned interface — never break it
silently.

### HR zones are config, not code
Manual HR zones live in `transform/seeds/hr_zones.csv`. Zone 2 is locked to
136–153 bpm (user's measured Zone 2). Do not hardcode zone boundaries in SQL —
always `ref('hr_zones')`.

### Streamlit caching
Any query that touches raw HR samples will scan millions of rows. Those
queries MUST be wrapped in `@st.cache_data` at the function boundary. Apply
it in `app/lib/queries.py`, not inside page files.

## Tooling commands

```bash
uv sync                                              # install / update deps
uv run ruff check .                                  # lint
uv run pytest                                        # unit tests
uv run dbt parse --project-dir transform \
  --profiles-dir transform                           # validate dbt project
uv run dbt build --project-dir transform \
  --profiles-dir transform                           # run all models + tests
uv run streamlit run app/home.py                     # launch app
uv run python -m ingest.flows.weekly_load            # run the ingest flow
```

## Git workflow

- Feature branches: `feat/`, `fix/`, `refactor/`, `docs/`
- Commit frequently with descriptive messages
- Never push directly to main
