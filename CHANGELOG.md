# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions `v0.1.0`–`v0.3.0` were backfilled from the conventional-commit history
(PRs #1–#33) and tagged retroactively at the commit that closed each milestone;
they group work by narrative arc rather than by release event.

## [Unreleased]

## [0.4.0] - 2026-06-05

Autonomy substrate, causal inference, and cross-source correlations — plus the
engineering-artifacts program (ADRs, diagrams, runbooks, CONTRIBUTING, this
changelog) and the mode-independent orchestrator reframe.

### Added
- **Cross-source correlations — schedule load.** `mart_daily_context` gains
  derived schedule-load signals (`meeting_span_hours`, `meeting_density`,
  `is_high_meeting_day`) computed from the existing calendar density, and page 09
  grows a "Schedule load → recovery" correlation grid alongside the weather grid
  — the "did 5 back-to-back meetings tank my HRV?" question, now answerable. The
  external-factors section is refactored into a shared `_corr_rows` / `_corr_heatmap`
  helper and gates the weather vs. schedule sub-grids independently. Adds the first
  golden-snapshot coverage for `mart_daily_context`
  (`tests/golden/mart_daily_context.json`). `mart_recovery_state` (public API) is
  untouched — correlation stays in the non-API `mart_daily_signals` lens.
- **Synthetic-warehouse autonomy substrate** — `ingest/synth` generates a
  deterministic, scenario-driven Apple-Health corpus the real loaders ingest
  unchanged, and `ingest/flows/make_demo_db` stands up the entire warehouse in an
  isolated `health_demo` DB (explicit-engine + `/health_demo` hard guard, pinned by
  `tests/test_demo_db_safety.py`) with **zero iOS export and zero credentials**.
- **Warehouse regression testing** — committed golden-snapshot tests for 9 marts
  (`tests/test_golden_marts.py`, `tests/golden/*.json`, `UPDATE_GOLDEN=1` to
  re-baseline), the flagship mart's first dbt 1.8+ **unit test** over every
  `recovery_signal` branch, and a CI **real-data gate** that builds the synthetic
  warehouse and runs the contract/unit/golden tests on populated tables.
- **Causal-Inference Lab** — `ingest/analysis/causal.py` (interrupted time series
  with Newey-West HAC errors, permutation/placebo p-values, difference-in-
  differences) → `raw.experiment_effects` → `stg_experiment_effects` →
  `mart_experiment_effects` (grain + `accepted_values` tests), an `experiments`
  seed, and the `13_experiments` Streamlit page. Validated by recovering a known
  effect *planted* in synthetic data (`tests/test_causal.py`).
- ADRs `0008` (statsmodels for causal inference, scoped exception to ADR-0006) and
  `0009` (Python results re-enter via raw→staging→mart); `docs/design/autonomous-build-plan.md`.
- Architecture Decision Records `docs/adr/0001`–`0007` capturing the seven
  hard-to-reverse decisions (TZ-at-staging, dedup priority, two-level idempotency,
  self-hosted Prefect, the `mart_recovery_state` public-API contract, pure-SQL
  Holt's forecasting, dbt-1.8 nested `accepted_values`), plus a `docs/adr/` index.
- `CHANGELOG.md` (this file), backfilled from PR history.

### Migration
- `scripts/init_raw_schema.sql` adds `raw.experiment_effects`. It is idempotent and
  purely additive (`CREATE TABLE IF NOT EXISTS`); apply it to an existing local
  `health` database before the next `dbt build`:
  `docker exec -i health_postgres psql -U health -d health < scripts/init_raw_schema.sql`.

## [0.3.0] - 2026-06-01

Forecasting, multi-consumer fan-out, and automation.

### Added
- Pure-SQL **Holt's-method forecasting**: `holt_forecast` macro + `mart_forecast_bands`
  and `mart_forecast_backtest`, with the `11_forecast` Streamlit page (#28).
- Second `mart_recovery_state` consumer — the **daily-workout-coach** skill
  (`scripts/daily_workout_coach.py`) (#27).
- Third `mart_recovery_state` consumer — the **Tempo PWA Firestore feed**
  (`scripts/push_recovery_state.py`), writing `users/{uid}/recovery_state/{latest,history}` (#32).
- Self-hosted **Prefect** weekly deployment (`flow.serve`, Sun 06:00 CT) with
  macOS launchd templates (#30).
- Tier-1 engineering docs: refreshed README, `docs/reference/data-dictionary.md`,
  and the `system-context.mmd` / `raw-erd.dbml` diagrams (#33).

### Changed
- VS Code launch configs added; `.claude/worktrees` gitignored (#29).

### Fixed
- `push_recovery_state_to_tempo` return-type annotation in the weekly flow.

## [0.2.0] - 2026-05-16

Breadth and hardening — sleep, enrichment, notifications, and CI/test rigor.

### Added
- **Sleep analytics stack**: `stg_categories` + hypnogram (`mart_sleep_stages`) +
  per-night scoring (`mart_sleep_nights`), later split from same-day naps via
  `int_sleep_periods` / `mart_sleep_naps` (#3, #24).
- HK **categories loader** (sleep stages, mindful sessions, HR-threshold events) (#2).
- Per-workout **heart-rate recovery** mart `mart_workout_hrr` (#17).
- **OpenWeather** day-summary loader + `mart_daily_context` (#19); Recovery-vs-external-factors
  section on page 09 (#20).
- **Google Calendar** density loader via secret iCal URL (#21).
- **Anomaly → push** notification pipeline (stdout + Pushover, YAML rules) (#23).
- Conversational **"Ask"** page — Claude over the marts (`10_ask.py`) (#26).
- dbt **source-freshness** checks on `raw.*` (#5); exposure declared for the
  weekly-health-review skill (#13); `rolling_trailing` macro (#12).
- **pre-commit / pre-push** hooks (ruff + mypy) (#6); page smoke tests (#14);
  end-to-end idempotency integration tests + safety-fixture regression guard (#7, #18, #22).

### Changed
- CI hardened with a Postgres service, mypy, coverage, and a full `dbt build` (#4).
- Per-metric observability in `weekly_load`; retry + structured ERROR alert on
  dbt-build failure (#8, #11).
- Refactors: shared idempotency helpers (#9), single-source Postgres engine (#15),
  sleep-duration backfill into anomaly/correlation views (#16).

### Fixed
- Non-destructive integration fixture preserves real local data (#18).
- Weather loader: explicit `api_key`/`lat`/`lon` — passing `None` means skip, not
  env-fallback (#25).

## [0.1.0] - 2026-04-29

Foundations — the end-to-end closed loop.

### Added
- Hash-based **file inventory** for idempotent CSV loading; raw-schema init script.
- **Idempotent quantities loader** + batch folder loader.
- dbt spine: `stg_quantities` → daily marts (RHR/HRV/VO₂ max/weight) →
  `int_workout_hr_samples` → `mart_workout_zones` → `mart_training_load` →
  **`mart_recovery_state`** (the public-API mart).
- **Workouts loader** + `stg_workouts`.
- Streamlit app: Daily, Weekly Review, Training Load + home landing.
- `weekly_health_review.py` briefing generator (first `mart_recovery_state` consumer).
- Prefect weekly flow with cron schedule (end-to-end).
- Portfolio-grade README + closed-loop architecture diagram; MIT license + badges;
  screenshots and command cheatsheet.

### Fixed
- ACWR chart bands share the x-scale with the line.

[Unreleased]: https://github.com/ksdisch/personal-health-elt/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/ksdisch/personal-health-elt/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ksdisch/personal-health-elt/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ksdisch/personal-health-elt/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ksdisch/personal-health-elt/releases/tag/v0.1.0
