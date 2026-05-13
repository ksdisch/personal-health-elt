# personal-health-elt — Project Backlog

Unprioritized list of features, improvements, refactors, and ideas for this project.
Pick items with the `project-backlog` skill in Claude Code.

**Item types:** Feature · Improvement · Refactor · Rebuild · Exploration · Bug

**How to add an item:** Under `## Open`, create a new `### [Type] Title` heading and fill in Why, Acceptance, Size, and Added.

---

## Open

### [Feature] Declare `exposure: weekly-health-review` for `mart_recovery_state`
- **Why:** The mart is contractually consumed by the external `weekly-health-review` Claude skill (per CLAUDE.md and the README's "public-API contract" cell), but no `exposures:` block exists in `transform/models/marts/schema.yml`. `dbt docs` and `dbt ls --select +exposure:` can't see the dependency, and contract drift can't be audited.
- **Acceptance:** `exposures:` block added in `transform/models/marts/schema.yml` with `type: application`, `depends_on: [ref('mart_recovery_state')]`, owner, and a description pointing at the skill. `dbt docs generate` renders the exposure node and the lineage graph shows the downstream consumer.
- **Size:** S
- **Added:** 2026-05-11

### [Improvement] Prefect: retries + failure alert on `run_dbt_build` task
- **Why:** `ingest/flows/weekly_load.py` invokes `run_dbt_build()` once with no retry logic. A transient Postgres restart or a flaky dbt compile silently kills the run from the operator's perspective — there's no notification path.
- **Acceptance:** `run_dbt_build` decorated with `@task(retries=2, retry_delay_seconds=60)`; on terminal failure the flow surfaces a non-zero exit AND emits a structured alert (Prefect log at ERROR with a tail of dbt stderr, or a Slack/email hook). Unit test simulates failure and confirms retry + final-failure logging.
- **Size:** S
- **Added:** 2026-05-11

### [Improvement] Per-metric observability in `weekly_load` flow
- **Why:** `weekly_load.py` summarizes `files_loaded` + `rows_inserted` in aggregate. On a partial failure it's impossible to tell from logs which metric family (HR, sleep, workouts) is broken or which CSV is misbehaving.
- **Acceptance:** Batch result includes per-loader and per-metric-type counts; flow logs a structured summary table (Prefect logger or JSON) at the end of each run; failing metric types are listed with sample paths and error type so an operator can immediately find the bad file.
- **Size:** S
- **Added:** 2026-05-11

### [Improvement] Extend smoke test to cover pages 01–04
- **Why:** `tests/test_smoke.py:18-24` parametrizes only pages 05–09. The four oldest, most-trafficked pages (01_daily, 02_weekly_review, 03_training_load, 04_body_comp) have no compile-time guard. They don't have the leading-digit gotcha, so `compile()` works the same on them.
- **Acceptance:** `NEW_PAGES` list expanded to all nine numbered pages under `app/pages/`; smoke test parametrizes over all of them; CI remains green.
- **Size:** S
- **Added:** 2026-05-11

### [Improvement] Extend mypy coverage to `app/`
- **Why:** The CI-hardening ship (2026-05-12) enabled mypy on `ingest/` but skipped `app/`. Reason: `app/pages/07_readiness.py:157` alone produces ~30 errors from a single `mark_text(**dict[str, object])` Altair kwarg spread, plus another ~30 at line 162. The signal-to-noise ratio for typing Streamlit + Altair page code is low — most errors are inherent to Altair's loosely-typed kwargs API, not real bugs. Worth revisiting once the page code stabilizes or Altair publishes better stubs.
- **Acceptance:** `uv run mypy app` passes cleanly. Likely requires: typing the Altair kwarg dicts at call sites (or using `cast(Any, ...)`), fixing the `Returning Any from function declared to return "Chart"` issues in `06_anomaly.py`, narrowing the `dict.get` arg type in `home.py`. CI's `Mypy (ingest)` step extended to `Mypy (ingest + app)`.
- **Size:** M
- **Added:** 2026-05-12

### [Improvement] README live-app link + `docs/DEPLOYMENT.md`
- **Why:** The README is portfolio-grade but has no "see it live" link and no deployment instructions. Hiring managers can't poke at the Streamlit app, and a fork can't reproduce the deployment story.
- **Acceptance:** README gains a "Live app" hero near the top with a deployed Streamlit URL (Streamlit Cloud / Fly / Railway). `docs/DEPLOYMENT.md` documents env vars, secrets, the Postgres provisioning step, the cold-start dataset import, and the redeploy path.
- **Size:** M
- **Added:** 2026-05-11

### [Refactor] Extract shared idempotency helpers across loaders
- **Why:** Three loaders (`quantities.py`, `workouts.py`, `categories.py`) now contain near-identical `_already_loaded()`, `_record_file()`, `_upsert_rows()`, and `_records_with_none_for_nan()` functions. The categories loader landed with the helpers duplicated by deliberate scope choice (consolidation deferred to keep the loader PR small). Adding a fourth source (e.g., weather, calendar, Oura) would mean a fourth copy.
- **Acceptance:** Helpers extracted to `ingest/loaders/_idempotency.py` (or a `BaseLoader` class); all three loaders import the shared versions; behavior unchanged (existing pytest + real-export idempotency check on categories still pass); unit test added for the extracted module.
- **Size:** S
- **Added:** 2026-05-11

### [Refactor] Extract rolling-window pattern into a dbt macro
- **Why:** `mart_training_load.sql` and `mart_daily_anomaly_bands.sql` compute trailing N-day windows with identical `rows between N preceding and 1 preceding` syntax. Adding a third consumer (e.g. Zone 2 trailing minutes on the readiness page) will mean a third copy-paste.
- **Acceptance:** New macro `transform/macros/rolling_trailing.sql` accepts `(column, window_days, partition_by)`. Both existing marts refactored to use it; `dbt build` produces row-for-row identical output (verify via a checksum diff before/after).
- **Size:** M
- **Added:** 2026-05-11

### [Refactor] Unify Postgres connection helper across ingest + app
- **Why:** `app/lib/queries.py` uses a SQLAlchemy `_engine()` factory while `ingest/loaders/*.py` calls `psycopg.connect(DATABASE_URL)` directly. Two ways to configure connection params, two places to debug auth failures, two places to update when secrets rotate.
- **Acceptance:** New `ingest/db.py` exposes `get_engine()` (cached) and `get_connection()` (raw psycopg). Loaders + `app/lib/queries.py` both import from it. `DATABASE_URL` parsing happens in exactly one place; existing tests still pass.
- **Size:** M
- **Added:** 2026-05-11

### [Improvement] Integration test for two-level idempotency contract
- **Why:** Existing tests mock the loaders at the unit level. No test runs a real CSV through a real Postgres twice and verifies the contract end-to-end: (a) second run is a no-op via the file-hash ledger, (b) partial failure leaves the ledger and rows in a consistent state, (c) overlap from two different files dedups via ON CONFLICT.
- **Acceptance:** Pytest fixture spins up a Postgres (or uses the dev container); test ingests the same fixture CSV twice and asserts `rows_inserted == N` then `== 0`, `file_inventory` has exactly one row, no duplicate rows in `raw.quantities`. Runs against the service container from item 8.
- **Size:** M
- **Added:** 2026-05-11

### [Exploration] dbt snapshot for resting-HR baseline drift
- **Why:** RHR shifts over months with fitness adaptation. Today `mart_recovery_state` compares "today vs. trailing 28d," but a proper SCD-2 snapshot would let downstream skills reason about "today vs. this-month's baseline" or surface inflection points (overtraining, illness onset). Open question: is the added complexity worth it for a single-user personal pipeline?
- **Acceptance:** A short writeup (in this item's notes or `docs/`) covering the decision (yes/no), the reasoning, and if yes — a working `transform/snapshots/snap_daily_rhr.sql` materializing weekly with `dbt_valid_from/to`, plus at least one row of historical drift captured.
- **Size:** L
- **Added:** 2026-05-11

### [Feature] Conversational "chat with your health" agent in Streamlit
- **Why:** Right now insight discovery is page-driven — you click around hoping to find the answer. A natural-language interface over the marts would let you ask "why was my recovery low last Tuesday?" or "show me weeks where my HRV crashed for 3+ days" and get a grounded answer with the relevant chart. This is the killer demo for an analytics-engineer portfolio: it proves your data model is good enough to answer arbitrary questions, not just the ones you anticipated.
- **Acceptance:** New Streamlit page `10_ask.py`. User types a question; Claude (via `anthropic` SDK) receives the question + a compact schema summary of `analytics_marts.*` + the row counts; emits a read-only SQL query; the page executes the query against Postgres, renders the result as a table and (when sensible) a chart, and Claude writes a one-paragraph explanation. SQL is restricted to `analytics_marts.*` SELECTs (no DDL, no `raw.*`). At least 5 example questions documented in the page sidebar.
- **Size:** L
- **Added:** 2026-05-11

### [Feature] Forecasting marts — predict next week's recovery and training load
- **Why:** Every existing mart looks backward. Adding forward-looking forecasts (next 7d RHR, HRV, ACWR, projected training load given a planned-workout slate) demonstrates real time-series chops and unlocks a much more useful workout planner: "if I run 8 miles tomorrow, here's where your ACWR lands." This is the most underrated analytics-engineer hiring signal — most candidates can build descriptive marts; very few build predictive ones.
- **Acceptance:** New `transform/models/marts/mart_forecast_*` family using either Prophet (Python) materialized via a `dbt-fal`-style hook OR a pure-SQL exponential-smoothing macro. Forecasts at least 7 days ahead for RHR, HRV, and ACWR. Streamlit page `11_forecast.py` shows the actuals + forecast band. Backtest report comparing 7d-out forecast vs. realized values for the last 12 weeks.
- **Size:** L
- **Added:** 2026-05-11

### [Feature] Cross-source enrichment — weather, calendar density, sleep environment
- **Why:** The single biggest unlock for actual insights. "Did 5 back-to-back meetings yesterday tank my HRV today?" "Does my recovery score drop on hot nights?" "Do I sleep worse the night after a high-stress workday?" None of these are answerable with Apple Health alone. Pulling OpenWeather, Google Calendar, and optionally Oura ring-temp / HomeKit bedroom-temp into the pipeline turns this from a logging tool into an insight engine — and lets you correlate behavior with biology.
- **Acceptance:** Three new ingest loaders (`weather_openweather.py`, `calendar_google.py`, optionally `oura.py`) landing in `raw.weather`, `raw.calendar_events`, `raw.oura_*`. New marts: `mart_daily_context` (joins weather + calendar density to the day), plus correlation columns added to `mart_recovery_state`. Streamlit "Correlations" page (already exists at 09) gets a new section: "Recovery vs. external factors."
- **Size:** L
- **Added:** 2026-05-11

### [Feature] Anomaly → notification pipeline (push to phone when recovery flags red)
- **Why:** Today the pipeline produces beautiful charts you have to remember to look at. The actual value of an early-warning system is realized only if it interrupts you when something is wrong — e.g., 3rd consecutive day of elevated RHR, HRV trending down 2σ, ACWR crossing into red. Closing the loop from data → action transforms this from a portfolio piece into something that genuinely changes behavior.
- **Acceptance:** New Prefect task `notify_on_state_change` reads `mart_recovery_state` after each weekly_load run, compares the latest state to the prior run's, and on red transitions (or any custom rule) sends a notification. At minimum: iMessage via the existing imessage MCP or Pushover/Slack webhook. Rules configurable via a YAML/seed file. Test mode where notifications go to stdout instead.
- **Size:** M
- **Added:** 2026-05-11

### [Refactor] Split "main sleep" from same-day naps in mart_sleep_nights
- **Why:** The noon-to-noon partition in `int_sleep_segments` correctly attributes nighttime segments to a wake date, but it lumps afternoon naps into the upcoming night's rollup. Real-data examples in `mart_sleep_nights` after the 2026-05-12 ship: 2026-04-14 reads 14.1 hours asleep / 15 awakenings / score 40.9, and 2026-04-16 reads 12.8 hours / 13 awakenings / score 57.8 — both are a nap + main sleep on the same calendar day, producing inflated time-in-bed and depressed efficiency. The composite score punishes the user for having napped.
- **Acceptance:** `int_sleep_segments` (or a new `int_sleep_periods`) detects gaps > ~2 hours between segments and treats each contiguous run as a distinct sleep period. `mart_sleep_nights` rolls up only the "main sleep" period (longest by duration) for the night. Optional: a sibling `mart_sleep_naps` for the secondary periods so napping isn't invisible. Re-run on real data, confirm Apr 14 / Apr 16 nights drop to plausible duration / awakening counts.
- **Size:** M
- **Added:** 2026-05-12

### [Refactor] Calibrate sleep score targets to personal baseline
- **Why:** `sleep_score_weights` ships with literature-derived targets (90% efficiency, 22% REM, 18% deep). Real-data averages from the first 29 nights show ~85% eff, ~17% REM, ~10% deep — deep% target is the consistent drag, sitting ~8 points below where lived experience lands. Two interpretations: (a) physiology genuinely runs low on deep and the score is honestly flagging that, or (b) the target is wrong for this user and a personal baseline would be more useful. Worth deciding deliberately rather than letting the default silently dictate "your score is bad."
- **Acceptance:** Once N ≥ 60 nights of real data, compute per-component 75th percentile from `mart_sleep_nights` and compare to literature targets. Decision documented in the seed comments or CLAUDE.md: either keep literature targets (and label `composite_score` as "vs sleep-science targets") or replace with personal-baseline targets. If swapped, update the seed CSV and re-run.
- **Size:** S
- **Added:** 2026-05-12

### [Feature] Natural-language → SQL agent over the marts
- **Why:** Distinct from the conversational chat agent (which answers questions and explains): this one is the power-user tool. You type a SQL-shaped request — "weeks where Zone 2 minutes exceeded 90 and HRV stayed above 60ms" — and get the literal query, a result table, and the ability to refine. Demonstrates the LLM-app pattern of treating the database schema as a prompt, and shows guardrails (read-only, schema-restricted, query-budget-limited).
- **Acceptance:** Streamlit page `13_query.py`. Claude receives the compact schema + a few-shot of example NL→SQL pairs; produces a query against `analytics_marts.*`; query runs with a `SET statement_timeout = 10s` and `LIMIT 10000`; result table + raw SQL shown side-by-side. Guardrails: queries blocked if they touch `raw.*` or contain DDL keywords.
- **Size:** L
- **Added:** 2026-05-11

### [Feature] Personal experiments framework — log interventions, measure pre/post effect
- **Why:** You try things: a new supplement, sleeping with windows open, fasted morning training, dropping caffeine after noon. Today there's no rigorous way to know if any of them moved the needle. A lightweight experiments framework lets you log "started magnesium 2026-04-01, stopped 2026-05-01," choose target metrics (RHR, HRV, sleep score), and get pre/post statistics with a confidence indication. Personal causal inference, productionized.
- **Acceptance:** Seed file `experiments.csv` (name, start_date, end_date, hypothesis, target_metrics). New macro `experiment_pre_post(experiment_name, metric, window_days)` computes mean/median/std for the N days before vs. during. New mart `mart_experiment_results`. Streamlit "Experiments" page: log a new experiment, view all past experiments with their effect sizes, and a small write-up generator (Claude summarizes results in plain English).
- **Size:** L
- **Added:** 2026-05-11

### [Feature] Workout-coach Claude skill — second downstream consumer of `mart_recovery_state`
- **Why:** Today `mart_recovery_state` has exactly one downstream consumer (`weekly-health-review`). Adding a second consumer — a daily workout-coach skill that reads recovery state + recent training load and suggests today's session (intensity, duration, zone target) — validates the public-API thesis and demonstrates the multi-consumer pattern that's the real point of having a contracted mart layer.
- **Acceptance:** New Claude skill `daily-workout-coach` in your skills directory. Reads `mart_recovery_state` (today's row) + `mart_training_load` (last 14 days) + your stated weekly plan from the vault. Outputs a recommendation card (session type, target zone, target duration, why). Skill is exercised at least once and the result captured in a daily note. Exposure for the new consumer added to `marts/schema.yml`.
- **Size:** M
- **Added:** 2026-05-11

### [Feature] Heart-rate recovery (HRR) mart — post-workout drop velocity
- **Why:** ACWR is great for load, but HRR — how fast your HR drops in the 60s after a hard interval — is one of the strongest individual fitness markers and you already have the raw HR samples to compute it. Each workout becomes a fitness datapoint. Trending HRR over months shows aerobic-capacity gains in a way RHR alone cannot.
- **Acceptance:** New mart `mart_workout_hrr` computed from `int_workout_hr_samples`: for each workout with a clear peak-HR moment, calculate HR drop at 30s / 60s / 120s post-peak. Joined to workout metadata so you can filter by activity type. New section on the Training Load page or a new "Fitness markers" page showing 30d/90d trend.
- **Size:** M
- **Added:** 2026-05-11

### [Feature] Auto-generated "Year in Review" report — quarterly + annual narrative
- **Why:** Strava Wrapped is a viral moment because the data is in your hands as a story, not a dashboard. Once a quarter / once a year, generate a long-form HTML or PDF report: training volume trends, biggest gains, worst weeks, seasonal patterns, recovery story, top correlations discovered. Claude writes the narrative; the marts provide the numbers. Becomes a sharable artifact and a hell of a portfolio piece.
- **Acceptance:** New Python script `reports/year_in_review.py` (or a Prefect flow) that queries the marts, hands the aggregates to Claude with a prompt template, and outputs `reports/2026-q2.html` (Tailwind + Altair charts) + a Markdown summary. Designed to be re-runnable for any time window. At least one full report committed to the repo for show.
- **Size:** L
- **Added:** 2026-05-11

### [Exploration] dbt Mesh — split into `health-core` + `analytics-derived` projects with cross-project refs
- **Why:** Today everything lives in one dbt project. Decomposing into `health-core` (raw → staging → trusted facts: heart rate, workouts, sleep) and `analytics-derived` (training load, recovery, anomaly bands, forecasts) using dbt's cross-project ref pattern is exactly the architecture senior analytics-engineer interviews probe for. The personal pipeline is the perfect size to actually do this without ceremony getting in the way.
- **Acceptance:** Writeup in `docs/dbt-mesh-spike.md` covering the proposed split, the boundary criteria, and (if proceeding) a working two-project layout with cross-project ref demonstrated end-to-end. Includes a "what I'd do differently in production" reflection.
- **Size:** L
- **Added:** 2026-05-11

### [Exploration] Semantic memory layer — vector store over journal + marts for long-horizon RAG
- **Why:** "When was the last time I felt this bad?" "Have I had a stretch like this before?" These questions require semantic search across years of daily notes + structured health data. A small vector store (Postgres `pgvector` extension, since you're already on Postgres) indexed over journal entries with embedded references to daily mart rows turns the pipeline into a real memory system. Speculative but very high upside.
- **Acceptance:** Writeup in `docs/semantic-memory-spike.md` evaluating: does it work? What's the recall on "find me weeks like this one"? Includes a working prototype (Streamlit page or notebook) showing at least 10 real queries with results.
- **Size:** L
- **Added:** 2026-05-11

### [Bug] Header-only category CSVs don't register in `raw.file_inventory`
- **Why:** During the categories loader rollout (PR #2), the otherwise-equivalent header-only files behaved inconsistently: `HKCategoryTypeIdentifierAudioExposureEvent.csv` (0 data rows) was registered in `raw.file_inventory`, but `HKCategoryTypeIdentifierLowHeartRateEvent.csv` (also 0 data rows) was not. Re-runs re-parse the unregistered file every time. Benign today (zero data rows = zero inserts either way) but a contract gap — `raw.file_inventory` is supposed to be a strict ledger of every file the loader has seen. The same inconsistency likely affects future header-only or sparse exports.
- **Acceptance:** The loader records a `file_inventory` row for every CSV it parses successfully, regardless of whether the resulting DataFrame is empty. Unit test covers the empty-DataFrame path and asserts the file ledger entry is written. Re-running on a header-only file is reported as `LoadResult(skipped=True)`, not re-parsed. Verified: a fresh ingest of `data/raw/export_full/` produces a `file_inventory` row for every `HKCategoryTypeIdentifier*.csv` on disk.
- **Size:** S
- **Added:** 2026-05-11

---

## In Progress

(none)

---

## Done

### [Improvement] Add `.pre-commit-config.yaml` (ruff + mypy)
- **Why:** CI lints on push but no local gate existed — issues were caught only after pushing a branch. For a portfolio repo, a pre-commit hook catches style + typing regressions before they hit a branch and also demonstrates dev-experience hygiene.
- **Acceptance:** `.pre-commit-config.yaml` at repo root runs `ruff check`, `ruff format --check`, and `mypy ingest` on `pre-commit` and `pre-push`. Hook install step documented in README.
- **Size:** S
- **Added:** 2026-05-11
- **Started:** 2026-05-12
- **Completed:** 2026-05-12 — branch `feat/pre-commit-hook`. Local hooks (`language: system`) so ruff + mypy versions never drift between the hook and CI's `uv` environment. Staged execution: `ruff check` + `ruff format --check` on `pre-commit` (fast, every commit); `mypy ingest` on `pre-push` (slower, only on push). Pre-shipped a one-time `ruff format .` mechanical reformat of 24 pre-existing-drift files (separate commit so the hook config reviews cleanly). mypy scoped to `ingest` to match CI — `app/` follow-up filed in the prior CI-hardening ship. Manual verification: `pre-commit run --all-files` and `pre-commit run --hook-stage pre-push --all-files` both pass.

### [Feature] Add source freshness checks on raw.{quantities,categories,workouts}
- **Why:** `transform/models/sources.yml` declared all three raw tables but set no `freshness:` or `loaded_at_field:`. For an ELT pipeline where ingest runs on a schedule, stale upstream data was a silent failure mode — a dead loader produced no warning until a Streamlit page rendered empty.
- **Acceptance:** `loaded_at_field: loaded_at` and `freshness: {warn_after: {count: 2, period: day}, error_after: {count: 7, period: day}}` set on all three sources; `dbt source freshness` runs cleanly and would warn/error if loads stop.
- **Size:** M
- **Added:** 2026-05-11
- **Started:** 2026-05-12
- **Completed:** 2026-05-12 — branch `feat/source-freshness`. Freshness placed at the source level (not per-table) since all three loaders share the weekly Sunday cadence. Real-data run on local Postgres surfaced immediate signal: `raw.categories` PASS (loaded recently during the sleep feature work), `raw.quantities` and `raw.workouts` ERROR STALE (>7 days since last ingest). That's the feature working as intended — those metric families need a re-export. Not wired into CI's `dbt build` step because (a) `dbt build` doesn't evaluate freshness by default and (b) CI runs against an empty-schema service container where freshness would always error.

### [Improvement] Tighten CI: mypy, coverage, and `dbt build` against a test Postgres
- **Why:** `.github/workflows/ci.yml` ran ruff + pytest + `dbt parse` only. mypy config existed in `pyproject.toml` but was unused; `pytest-cov` was a dev dep but no coverage was produced; `dbt parse` didn't execute models, so type mismatches in compiled SQL slipped through to user-verify time (e.g., the bare `asleep` value the synthetic-data sandbox missed during the sleep feature ship).
- **Acceptance:** CI runs mypy, `pytest --cov`, and `dbt build` against a Postgres service container with empty `raw.*` tables. Coverage printed; failing types or models fail the workflow.
- **Size:** M
- **Added:** 2026-05-11
- **Started:** 2026-05-12
- **Completed:** 2026-05-12 — branch `feat/ci-hardening`. New `ci.yml` adds postgres:16 service container (health/health/health to match docker-compose), a raw-schema init step (`psql -f scripts/init_raw_schema.sql`), `Mypy (ingest)`, `pytest --cov=ingest --cov=app --cov-report=term-missing --cov-report=xml`, and `dbt build` against the empty schema. Local mypy fixes: cast SQLAlchemy `scalar_one()` results to `int` in all three loaders' `_upsert_rows`; loosen `batch.load_folder` callable defaults to `Callable[..., Any]` (each loader's `LoadResult` dataclass is distinct, even though structurally identical); fix dict.get with `str | None` key; type `weekly_load` return as `dict[str, int | None]`; update Prefect `serve()` call to use `schedules=[Cron(...)]` (the `timezone=` kwarg was removed in Prefect 3.x). mypy scoped to `ingest/` only — `app/` mypy work filed as follow-up because Altair's `**dict[str, object]` kwarg spread produces ~60 errors with low signal value. Local verification: `mypy ingest` clean (10 source files), `pytest --cov` 51/51 at 45% coverage, `dbt build` 117/117 PASS on real Postgres.

### [Feature] Sleep-stage hypnogram + composite sleep-quality mart
- **Why:** Sleep is the single biggest lever on recovery, and right now this pipeline doesn't analyze it at all — even though Apple Health exports stage-level data. Once the categories loader lands (item 1), build the actual sleep showpiece: hypnogram visualization (REM/Deep/Light/Awake bands by time), per-night composite score (efficiency × REM% × deep% × fragmentation penalty), and a 28-day sleep trend page.
- **Acceptance:** New marts `mart_sleep_nights` (one row per night with efficiency, REM minutes, deep minutes, awake count, composite score) and `mart_sleep_stages` (stage-level grain for hypnogram). New Streamlit page `12_sleep.py` showing tonight's hypnogram, 14-day trend, and a "what's hurting your sleep score" breakdown. Composite score formula documented and parameterized in a seed.
- **Size:** L
- **Added:** 2026-05-11
- **Started:** 2026-05-12
- **Completed:** 2026-05-12 — branch `claude/select-backlog-feature-bnfKN`, commits `a16434a` (feat) + `76c9508` (fix). Local `dbt build --select +mart_sleep_nights +mart_sleep_stages` green: 1 seed + 1 view (`int_sleep_segments`) + 2 tables + 29 data tests, PASS=34 TOTAL=34. Real-data run on 830 SleepAnalysis rows: `mart_sleep_nights` materialized 29 nights spanning 2026-03-21 → 2026-04-20, avg sleep_efficiency_pct=85.7%, avg composite_score=65.3, avg time_asleep_hours=6.83, avg awakenings=7.2. `mart_sleep_stages` materialized 830 rows: asleepCore 361 / awake 208 / asleepREM 147 / asleepDeep 92 / asleep 22. **Iter-1 catch:** real-data accepted_values test flagged a 7th sleep_stage value the synthetic fixtures missed — bare `asleep` (no stage suffix), 22 rows from April 5-14 from a source that records sleep without stage decomposition. Fix bucketed it into `unspecified_asleep_min` and added an "Asleep (unstaged)" band to the hypnogram legend. Composite score formula (weights 0.40 eff / 0.30 REM / 0.30 deep, fragmentation penalty 1.5 pts/awakening, targets 90% eff / 22% REM / 18% deep) lives in `sleep_score_weights` seed for easy tuning. Streamlit page `app/pages/12_sleep.py` renders last-night metric cards, hypnogram (Altair mark_rect by stage band), 14-day composite_score + efficiency trend, and a component-contribution bar chart. **Known limitation:** the noon-to-noon night attribution lumps afternoon naps into the upcoming night's rollup, producing two-segment "nights" with inflated time-in-bed (Apr 14 = 14.1hr asleep / Apr 16 = 12.8hr — both correspond to a nap + main sleep). Future refinement: sub-segment "main sleep" vs "naps" within a calendar day.

### [Feature] Add `stg_categories.sql` staging model
- **Why:** The categories loader landed (PR #2) and 1542 rows sat in `raw.categories` across five populated HK category types, but no staging model existed. Without `stg_categories.sql` the data was invisible to dbt's intermediate/marts layers and to the Streamlit app. The sleep-stage hypnogram feature and any other category-derived insight was blocked on this. Categories also needed the same TZ-normalization + multi-source dedup pattern as `stg_quantities` (Apple Watch > iPhone > third-party).
- **Acceptance:** `transform/models/staging/stg_categories.sql` materializes as a view, strips the `HKCategoryTypeIdentifier` prefix, converts UTC → America/Chicago (TZ owned by staging per CLAUDE.md), applies the `source_priority` window function for multi-source dedup, filters to `source_rank = 1`. `transform/models/staging/schema.yml` documents every returned column with appropriate `not_null` / `accepted_values` tests (the seven HK types covered in `accepted_values`). `dbt build --select +stg_categories` is green.
- **Size:** S
- **Added:** 2026-05-11
- **Started:** 2026-05-12
- **Completed:** 2026-05-12 — branch `claude/select-backlog-feature-bnfKN`, commit `f8aa794`. Local `dbt build --select +stg_categories` green: 1 view + 6 tests, PASS=7 TOTAL=7. View materializes at `analytics_staging.stg_categories` with 1542 rows across five types (matches raw exactly — no dedup drops): SleepAnalysis (830), AppleStandHour (704), MindfulSession (5), HeadphoneAudioExposureEvent (2), HighHeartRateEvent (1). Dedup invariant verified (zero `(category_name, start_ts_local)` collisions). TZ round-trip spot-checked on SleepAnalysis (UTC↔CDT offset = 0). The two zero-row types (`AudioExposureEvent`, `LowHeartRateEvent`) are in the `accepted_values` list pre-emptively so a future export populating them parses without test failure. Unblocks `int_sleep_nights` / sleep-hypnogram feature.

### [Feature] Implement categories loader for sleep stages, mindfulness, audio events
- **Why:** `ingest/loaders/categories.py:13` was a `NotImplementedError` stub. Six HK category types (SleepAnalysis, MindfulSession, AudioExposureEvent, HighHeartRateEvent, LowHeartRateEvent, AppleStandHour) were exported by Health Auto Export but skipped at ingest, so sleep-stage analytics, mindful minutes, and audio-exposure events were unavailable to dbt.
- **Acceptance:** `load_categories_csv(path)` implemented with the same two-level idempotency contract as quantities/workouts (SHA file ledger + ON CONFLICT row dedup, single transaction); categories dispatched in `ingest/loaders/batch.py`; rows land in `raw.categories`; re-running on the same file is a no-op; at least one row per category type observable in the warehouse after a real export.
- **Size:** M
- **Added:** 2026-05-11
- **Started:** 2026-05-11
- **Completed:** 2026-05-11 — PR #2. Real-export run inserted 1542 rows across SleepAnalysis (830), AppleStandHour (704), MindfulSession (5), HeadphoneAudioExposureEvent (2 — generic loader handled a 7th type cleanly), HighHeartRateEvent (1). Second flow run inserted 0 rows; idempotency contract holds. ruff clean, pytest 50/50, dbt build 83/83. Three follow-ups filed above.
