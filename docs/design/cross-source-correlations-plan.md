# Plan — Cross-source correlations: surface schedule load on page 09

**Branch:** `feat/cross-source-schedule-correlations`
**Milestone source:** ROADMAP "Next" → BACKLOG _Cross-source enrichment — weather,
calendar density, sleep environment_. Selected via `/autonomous-milestone`.
**Status legend:** ☐ todo · ◐ in progress · ☑ done

## Why this is the real gap (deep-dive finding)

The cross-source feature is **~80% already shipped**: the weather + calendar
loaders, `raw.weather` / `raw.calendar_daily`, `stg_weather` / `stg_calendar`,
`mart_daily_context` (weather **and** calendar columns), and a page-09 "Recovery
vs. external factors" section (#20) all exist. The synthetic `health_demo`
warehouse also generates 120 deterministic days of weather **and** calendar, so
the whole thing is verifiable with **zero credentials**.

What is genuinely missing — and maps directly to the backlog's stated driving
questions:

1. **Calendar density never reaches the UI.** `mart_daily_context` carries
   `timed_event_count / hours / all_day_event_count`, but `daily_context()`
   SELECTs weather columns only, and page 09's external grid wires only weather
   predictors. The headline question — _"did 5 back-to-back meetings yesterday
   tank my HRV today?"_ — is **unanswerable** in the app today.
2. **No derived schedule-load signal.** Only raw counts/hours exist; there is no
   density / fragmentation / "high-meeting day" metric. The mart header even
   says derived calendar metrics belong in `mart_daily_context`.
3. **`mart_daily_context` has no golden snapshot** — the one enrichment mart
   with zero regression coverage.

Stale acceptance note: the backlog line _"correlation columns added to
`mart_recovery_state`"_ predates the frozen public-API contract. The project
evolved correlation into the non-API `mart_daily_signals` lens + page 09. We
honor that — **`mart_recovery_state` is not touched.**

## Scope / non-goals

- **In:** derived schedule-load signals in `mart_daily_context`; surface calendar
  predictors as a new "Schedule load → recovery" correlation grid on page 09;
  golden + schema-test coverage for the mart; docs.
- **Out (future):** Oura ring temp / HomeKit (backlog marks "optionally");
  planting a synthetic calendar→HRV effect; the OpenWeather 401 fix (separate).
- **Frozen:** `mart_recovery_state.sql` (public API). Page 09 reads it only via
  the `mart_daily_signals` lens, never directly.

## Steps

### Phase 1 — dbt: derived schedule-load signals + coverage
- ☐ `transform/models/marts/mart_daily_context.sql` — add a `calendar` CTE that
  derives, from the existing density columns:
  - `meeting_span_hours` = hours between first and last timed event (NULL when
    no/instant events)
  - `meeting_density` = `timed_event_hours / nullif(meeting_span_hours, 0)` —
    share of the active window actually in meetings (back-to-back proxy; ~1.0 =
    packed, low = spread out)
  - `is_high_meeting_day` = `coalesce(timed_event_count, 0) >= 5` (encodes the
    "5+ meetings" question directly)
- ☐ `transform/models/marts/schema.yml` — document the 3 new columns; `not_null`
  on `is_high_meeting_day`; refresh the mart description (calendar now real).
- ☐ `tests/test_golden_marts.py` — add `mart_daily_context` to `GOLDEN_MARTS`
  (`order_by: ["day"]`).

### Phase 2 — app: surface calendar predictors
- ☐ `app/lib/queries.py` `daily_context()` — extend SELECT to include the
  calendar density + 3 derived columns; refresh docstring (calendar is real).
- ☐ `app/pages/09_correlations.py` —
  - extract the duplicated Pearson-grid build into a `_corr_grid` /
    `_heatmap` helper (used by the weather grid and the new calendar grid);
  - add a **"Schedule load → recovery"** grid (yesterday's meeting
    count / hours / density / high-meeting flag → today's HRV / RHR / sleep /
    recovery);
  - gate weather and schedule sub-grids independently (each renders only when
    its source has data), fixing the weather-only empty-state;
  - update the Method + caveats expander (schedule lag, density definition,
    correlation ≠ causation); fix the stale "sleep duration will appear once
    categories.py is implemented" docstring (already implemented).

### Phase 3 — verify (on synthetic `health_demo`, no creds)
- ☐ `uv run python -m ingest.flows.make_demo_db` (rebuild; runs dbt build+tests)
- ☐ `UPDATE_GOLDEN=1 uv run pytest tests/test_golden_marts.py -k mart_daily_context`
  then full `tests/test_golden_marts.py` green (confirm no other mart drifted)
- ☐ `uv run ruff check .` · `uv run pytest` · `uv run dbt parse`
- ☐ page-09 syntax/compile smoke test
- ☐ launch Streamlit against `health_demo` (`POSTGRES_DB=health_demo`), screenshot
  page 09, confirm the schedule-load grid renders
- ☐ independent `verifier` subagent gate

### Phase 4 — docs + PR
- ☐ `CHANGELOG.md` [Unreleased] entry
- ☐ `BACKLOG.md` cross-source entry — mark calendar surfacing + derived signals
  done; note Oura/HomeKit still future
- ☐ conventional commits; open PR to `main`

## Risk notes
- Synthetic calendar is independent of recovery, so correlations will be
  near-zero on `health_demo` — expected; we verify plumbing/empty-states/render,
  not a planted effect (same as the existing weather grid).
- `meeting_density` can exceed 1.0 with overlapping events — informative, left
  uncapped, documented.
- No dbt model `ref()`s `mart_daily_context`, so new columns are purely additive.

## Outcome (2026-06-05) — complete

All phases done. Verified on the synthetic `health_demo` warehouse (zero creds):

- **dbt:** `make_demo_db` rebuild → full `dbt build` green incl. the new
  `not_null(is_high_meeting_day)` test. Derived columns compute sensibly on the
  120-day corpus: 52 high-meeting days, `meeting_density` 0.08–1.22 (the >1.0
  overlap case occurs and is documented), 9 sparse days correctly NULL.
- **Golden:** `mart_daily_context` baselined (120 rows); full golden suite
  **12 passed** — additive change drifted no other mart.
- **Quality gate:** `ruff` clean · `pytest` **241 passed, 1 skipped** (intentional
  fixture-safety skip) · `dbt parse` clean.
- **Visual smoke test:** launched Streamlit against `health_demo`, drove the real
  UI (kapture). Page 09 rendered without exception; DOM confirmed three Vega
  heatmaps (main + weather + schedule); the "Schedule load → recovery" grid shows
  the 4 calendar predictors × 4 outcomes with real Pearson values and the
  "correlation ≠ causation" caption. Near-zero r's are expected — synthetic
  calendar is independent of recovery; the sleep-outcome column shows "—" because
  the demo corpus carries no sleep-category data (graceful, not a crash).
- **`mart_recovery_state` (public API): untouched.**
