# CLAUDE.md — context bridge for `personal-health-elt`

This file is the durable context that any Claude Code session should read before
touching this project. It captures decisions that aren't obvious from the code
alone.

## What this project is

A personal Apple Health ELT pipeline. The **Simple Health Export CSV** iOS app
writes CSVs (the loaders are coded to its schema — `sep=,` hint line + columns
`type, sourceName, productType, startDate, endDate, unit, value`); Python
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
  categories, workouts), Prefect flows. Also `synth/` (deterministic synthetic
  corpus generator) and `analysis/causal.py` (the causal-inference engine).
- `transform/` — dbt project root. Staging / intermediate / marts models,
  seeds, tests, macros.
- `app/` — Streamlit app. `home.py` + numbered pages under `pages/`.
- `tests/` — pytest unit tests (separate from dbt tests, which live under
  `transform/tests/`).
- `data/raw/` — export drop folder (overridable via `HEALTH_EXPORT_PATH`;
  in practice pointed at an iCloud Drive folder so the iOS export syncs in —
  see `docs/automation.md`). Gitignored.
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
This mart now has **two downstream consumers**: the `weekly-health-review`
Claude skill (Markdown briefing path) and the Tempo PWA's Rhythm view
(Firestore feed path via `scripts/push_recovery_state.py` →
`users/{uid}/recovery_state/{latest,history}`). Schema changes (renaming a
column, dropping a field, changing a unit) require updating BOTH consumers
in lockstep. Treat the mart like a versioned interface — never break it
silently. The dbt `accepted_values` test on `recovery_signal` and the
`unique(day)` test in `transform/models/marts/schema.yml` are the durable
contract surface for both consumers.

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
uv run python -m ingest.flows.make_demo_db           # build the synthetic
                                                     # health_demo warehouse
                                                     # (no real data / creds);
                                                     # then: UPDATE_GOLDEN=1 uv run
                                                     # pytest tests/test_golden_marts.py
```

## Git workflow

- Feature branches: `feat/`, `fix/`, `refactor/`, `docs/`
- Commit frequently with descriptive messages
- Never push directly to main
- Stage files by name (`git add path/to/file ...`). Never `git add -A` or
  `git add .` — too easy to accidentally include `.env`, `data/raw/*.csv`,
  or `transform/target/`.

## Orchestrator workflow

For multi-phase tasks (more than ~2 areas of the repo touched), this
project uses an orchestrator-worker pattern. Artifacts:

- `.claude/orchestrator-prompt.md` — copy-paste to start a new
  orchestrator session
- `.claude/agents/` — named specialist subagents
  (`dbt-modeler`, `streamlit-page-wright`, `verifier`, `loader-engineer`)
- `.claude/templates/phase-brief.md` — the template the orchestrator
  fills in for every worker dispatch

Default style is **hybrid**: phases run sequentially; within a phase the
orchestrator MAY fan out to multiple parallel `Agent` calls. The
orchestrator coordinates only — it does not run shell, edit files, or
read code directly. Every concrete action is dispatched.

> **Mode note:** the "coordinates only" rule is the §3.2 high-oversight
> dispatch mode. Autonomous runs use §3.1 — a single session plans, builds,
> tests, and opens a PR directly, with no mandatory dispatch ceremony. See
> §3 and §4 of `.claude/orchestrator-prompt.md` for the full mode rules and
> precedence. Invariants (§1) and gates (§2) apply in both modes.

## Conventions for subagents (every worker inherits these)

- **Stay in scope.** Edit ONLY the files listed under "Files in scope" in
  the phase brief. Surface anything outside that list as OPEN QUESTIONS.
- **Two-attempt rule.** If a fix fails twice, STOP and return OPEN
  QUESTIONS — don't keep iterating or loosen tests to make things pass.
- **No destructive shortcuts.** Never `--no-verify`, `rm -rf`,
  `dbt run-operation` for cleanups, `git reset --hard`, or `git push`
  unless the brief explicitly authorizes it.
- **`mart_recovery_state.sql` is off-limits** unless the brief explicitly
  authorizes a contract change (which also requires updating the
  `weekly-health-review` skill in lockstep).
- **Tests can fail for a reason.** If a dbt test or pytest fails, read
  the compiled SQL / test source first. Decide whether the test is wrong
  or the change is wrong. Don't loosen the test without a written reason.

## Project-specific gotchas

- **Numeric-leading page modules.** `app/pages/05_year_view.py` cannot be
  imported via `import app.pages.05_year_view` (Python syntax error on the
  leading digit). For smoke tests, use `compile(open(path).read(), path,
  "exec")` for a syntax-only check, or `importlib.util.spec_from_file_location`
  + `exec_module` if you actually need to run the module.
- **`accepted_values` test syntax.** dbt 1.8+ uses the nested form:
  ```yaml
  - accepted_values:
      arguments:
        values: [a, b, c]
  ```
  The old top-level `values:` form will silently no-op.
- **Schema layouts.** Marts → `analytics_marts.*`, intermediate →
  `analytics_intermediate.*`, staging → `analytics_staging.*`, raw →
  `raw.*`. The app layer always queries the `analytics_*` schemas, never
  `raw.*` or `public.*`.
- **`dbt build --select +model` vs `model+`.** `+model` = build all
  upstream deps + the model. `model+` = build the model + everything
  downstream. Use `+model` when adding a new model to a fresh DB.
