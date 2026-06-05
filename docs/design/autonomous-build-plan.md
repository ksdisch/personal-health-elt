# Autonomous Build Plan — Synthetic Warehouse + Causal-Inference Lab

> **Status:** ✅ delivered on branch `feat/synthetic-warehouse-causal-lab`
> (both phases built, verified, and committed; full pytest 240 passed, dbt build
> green on a from-scratch `health_demo`). Open item: apply the idempotent
> `scripts/init_raw_schema.sql` migration to the real `health` DB to pick up
> `raw.experiment_effects` before the next build there.
> **Provenance:** milestone selected from a multi-agent brainstorm (43-agent
> ranked shortlist); this plan was hardened against the repo's actual
> mechanics. It doubles as the *designed autonomous workflow* — the contract a
> Claude Code ultracode run follows to plan → implement → test → verify both
> phases with **no human in the loop**.

## Why this milestone

The pipeline already ships forecasting, anomaly→notification, sleep marts, an
NL "Ask" agent, and three `mart_recovery_state` consumers — but **every
"real-data" verification path depends on a human-provided iOS export** loaded
into the dev's local Postgres. CI even admits its tests "pass trivially on
empty inputs." That human-data dependency is the #1 blocker to full autonomy,
and the flagship public-API mart has **zero SQL branch coverage**.

- **Phase 0 — Synthetic Warehouse** deletes that dependency: a deterministic,
  scenario-driven Apple-Health corpus generator that lets a fresh agent stand
  up the entire 17-mart warehouse from a bare clone and machine-prove every
  model. It is the **autonomy substrate**.
- **Phase 1 — Causal-Inference Lab** is the headline advancement built *on*
  that substrate: the project's first *causal* layer (ITS + DiD + permutation
  inference), validated by **recovering an effect the Phase-0 generator
  plants**. Phase 0 builds the oracle that proves Phase 1.

## Isolation design (validated)

The dev DB `health` holds real data and must never be touched.

- **Loading** uses **explicit engine injection** — `load_folder(folder,
  engine=demo_engine)` where `demo_engine = create_engine(<…/health_demo>)`.
  This is exactly what `ingest/db.py` recommends and sidesteps the
  `@lru_cache`/import-time-`DATABASE_URL` footgun entirely (no env mutation,
  no monkeypatching).
- **dbt** runs as a **subprocess** with `POSTGRES_DB=health_demo` in its env
  (`transform/profiles.yml` is fully env-driven).
- **Hard guard:** `make_demo_db` refuses to run unless the resolved engine URL
  ends in `/health_demo`, and asserts the target DB name ≠ `health`. A safety
  regression test (`tests/test_demo_db_safety.py`, mirroring
  `tests/test_fixture_safety.py`) pins this.
- `health_demo` is created + bootstrapped from `scripts/init_raw_schema.sql`
  (idempotent). ✅ already created; raw.* empty; real `health` untouched.

## Determinism design (golden diffs must not flake)

- The corpus is anchored to **fixed 2024 calendar dates** (e.g.
  `2024-01-01 … 2024-04-30`). Because that is firmly in the past,
  `is_today = (day = current_date)` is deterministically `false` and
  `days_since_last_workout` is data-relative → stable.
- Golden digests cover a **curated stable-column allowlist per mart** and
  **exclude** any column whose SQL references `current_date` / `now()` /
  `loaded_at`, plus forecast/anomaly "future projection" columns anchored to
  the run date. Floats are canonicalised (rounded, sorted-key JSON).
- `--update-golden` is gated (explicit flag/env) so a bare `dbt build` can
  never silently re-baseline over a real regression.

## Scenario → `recovery_signal` branch map (verified against the mart)

`mart_recovery_state` branches, in order:

| Scenario | How the corpus drives it | Asserted `recovery_signal` |
|---|---|---|
| cold-start | ~5–7 days, RHR+HRV only, no workouts → `chronic_load=0` → `acwr` NULL and/or `hrv_7d_prior` NULL | `insufficient_data` |
| overtraining | ~28d steady load baseline + late load spike → `acwr > 1.5` | `strained` |
| hrv-crash | steady load (`acwr` ≤ 1.5) + final-day HRV < 0.85× trailing-7d-prior | `strained` |
| well-recovered | steady load `acwr ∈ [0.8,1.3]` + HRV ≥ 0.95× prior | `well_recovered` |
| normal | steady, none of the above | `neutral` |

The default `full` corpus stitches all of these across one ~120-day timeline
so a single golden snapshot covers **every** `recovery_signal` value, and a
pytest asserts each value appears ≥ 1×.

## Loader/CSV contract (verified)

- Quantities CSV cols (after optional `sep=,` line): `type, sourceName,
  sourceVersion, productType, device, startDate, endDate, unit, value`
  (UTC ISO). Filename must contain `HKQuantityTypeIdentifier`; the `type`
  column carries the full identifier (staging strips the prefix).
- Workouts CSV: `sourceName, sourceVersion, productType, startDate, endDate,
  activityType, duration, totalEnergyBurned ("659.283 kcal"), totalDistance
  ("9688.1 m"), HKElevationAscended, HKElevationDescended, HKMaximumSpeed,
  HKIndoorWorkout (0/1)`. Filename contains `HKWorkoutActivityType`.
- Categories CSV (sleep): `type` = `HKCategoryTypeIdentifierSleepAnalysis`,
  `value` carries the stage; filename contains `HKCategoryTypeIdentifier`.
- Idempotency: SHA256-of-file ledger + row-level `ON CONFLICT`. Re-running
  `load_folder` over the same files inserts **0** rows.
- `raw.weather` / `raw.calendar_daily` are credential-gated (not routed by
  `batch.py`) → the generator writes them **directly** via the demo engine.

## Work items (dependency-ordered)

### Phase 0
- **P0-1** `ingest/synth/` corpus generator (fixed seed; scenarios; in-workout
  HeartRate; multi-source overlap; sleep categories; direct weather/calendar).
- **P0-2** `ingest/flows/make_demo_db.py` (+ `python -m` entrypoint): create
  health_demo → init schema → generate → `load_folder(engine=demo)` → weather/
  calendar direct insert → `POSTGRES_DB=health_demo dbt build` subprocess. Hard
  URL guard. `tests/test_demo_db_safety.py`.
- **P0-3** Golden harness `tests/test_golden_marts.py` + committed
  `tests/golden/*.json`; stable-column allowlist; `--update-golden` gate;
  self-skips when health_demo absent. Branch-coverage assertion.
- **P0-4** dbt unit tests (1.8+, nested `arguments:`) on `mart_recovery_state`,
  `mart_daily_anomaly_bands`, `mart_sleep_nights` (fallback to golden for
  window-heavy cases that the given-rows fixture can't express).
- **P0-5** CI: 2nd job loads the synthetic corpus + runs full `dbt build` +
  `dbt test` + golden harness against **populated** tables.

### Phase 1
- **P1-1** `uv add statsmodels`; `ingest/analysis/causal.py` — segmented-
  regression ITS (Newey-West HAC), DiD, permutation/placebo p-values. DB-free
  unit test: HAC SE ≠ naive OLS SE on autocorrelated input.
- **P1-2** ADRs: supersede/extend ADR-0006 (statsmodels for *causal* while
  forecasting stays pure-SQL); data-flow ADR (Python results → `raw.
  experiment_effects` → staging → mart keeps layering honest).
- **P1-3** `transform/seeds/experiments.csv`; `stg_experiment_effects`;
  `mart_experiment_effects` (+ schema.yml singular grain test = one row per
  experiment×target_metric; washout guard). Wire `mart_daily_context`
  (weather/calendar) as exogenous controls.
- **P1-4** `app/pages/13_experiments.py` (mirror `11_forecast`): segmented-fit
  + counterfactual + effect cards with HAC p / placebo p / n caveats; optional
  graceful-skip Claude verdict. Cached queries in `app/lib/queries.py`.
- **P1-5** Planted-effect oracle: a generator scenario plants a known step/
  slope; pytest asserts the engine recovers it within a generous fixed-seed
  tolerance, and a no-effect negative control yields a **high** placebo p.

### Cross-cutting / docs
- **X-1** README "What this demonstrates" rows (reproducible test data;
  warehouse regression testing; causal inference); rewrite ci.yml "pass
  trivially" comment; BACKLOG→Done + CHANGELOG entries.

## Verification sequence (the autonomous gate)

1. `uv run ruff check .` + `uv run pytest` (existing suite) green — no
   regressions; safety tests pass.
2. `python -m ingest.flows.make_demo_db` → generate → load → `dbt build` on
   health_demo all succeed.
3. **Idempotency:** re-run the demo load → **0** new rows.
4. **Branch coverage:** every `recovery_signal` value present in health_demo.
5. **Golden teeth:** golden harness green; then on a scratch edit, perturb one
   mart → golden goes **RED**; revert.
6. `POSTGRES_DB=health_demo dbt test` green (incl. unit tests); flip one unit-
   test threshold → it goes **RED**; revert.
7. **Planted-effect oracle:** `dbt build --select +mart_experiment_effects` on
   the planted corpus; pytest recovers the known effect; negative control →
   high placebo p; HAC-SE ≠ OLS-SE unit test green.
8. Headless `streamlit run app/home.py` + browser-MCP screenshots of pages
   `01` (daily), `06` (anomaly), `11` (forecast), `13` (experiments) rendering
   against health_demo.
9. Final: full `uv run pytest` + `uv run dbt build` + `ruff` green; independent
   `verifier` pass.

## Autonomy guardrails (every execution agent obeys)

- Work only on branch `feat/synthetic-warehouse-causal-lab`. Stage files by
  name; never `git add -A`. **No push** without explicit user go-ahead.
- `mart_recovery_state.sql` is **off-limits** — Phase 1 is purely additive and
  must not edit it. The golden harness/unit tests *read* it; they never change
  it.
- Two-attempt rule: if a fix fails twice, stop and surface OPEN QUESTIONS;
  never loosen a test without a written reason.
- dbt 1.8+ `accepted_values` uses the nested `arguments: { values: [...] }`
  form. Numeric-leading page modules (`13_experiments`) use
  `compile()`/`spec_from_file_location` for smoke tests.

## Deferred human follow-ups (off the critical path)

- `git push` / opening a PR (needs explicit go-ahead).
- Live Pushover receipt, live Firestore write, GitHub Pages publish, Claude
  Desktop MCP handshake — none are on this milestone's path; verified via
  dry-run / in-process where touched.
- Modeling judgment with no automated oracle (DiD control-metric default) is
  ADR'd with a defensible default; the ITS+permutation leg is load-bearing.
