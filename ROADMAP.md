# Roadmap

A forward-looking **now / next / later** view of where `personal-health-elt` is
headed. This is the *narrative* layer; the detailed, typed entries
(Why · Acceptance · Size · Added) live in [`BACKLOG.md`](BACKLOG.md), and shipped
work is recorded in [`CHANGELOG.md`](CHANGELOG.md). Each item below links back to
its backlog entry.

> **How to read this:** *Now* is in flight or next 1–2 weeks. *Next* is roughly
> this quarter. *Later* is a deliberate parking lot — high-upside bets that are
> scoped but not yet scheduled. Re-prioritized quarterly (see the maintenance
> cadence in [`docs/artifacts-plan.md`](docs/artifacts-plan.md)).

_Last updated: 2026-06-03._

---

## Now — in flight / next 1–2 weeks

Closing out the engineering-artifacts program (portfolio-credibility weighting)
and landing the one remaining front-door task.

- **Engineering-docs program — Tier-2 closeout + drift guards.** README refresh,
  data dictionary, ADRs 0001–0007, CHANGELOG + tags, and the system/lineage/
  sequence diagrams have all shipped. Remaining: this Tier-2 batch (ROADMAP +
  postmortem template + flow-failure runbook), then the **drift-guard CI**
  (mermaid-lint, `dbt docs generate`, a doc-freshness pytest, DBML-validate) and
  the **Tier-3 docs** (forecasting design doc — backed by
  [ADR-0006](docs/adr/0006-pure-sql-holt-forecasting.md) — `CONTRIBUTING.md`,
  `justfile`, SLO freshness note). Tracked in
  [`docs/artifacts-plan.md`](docs/artifacts-plan.md).
- **Live-app URL.** Deploy the Streamlit app per [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
  and replace the README "Live app" TODO with the real link — the last step that
  makes the portfolio link actually clickable for a reviewer.
  → [BACKLOG: Fill in the README "Live app" URL](BACKLOG.md#improvement-fill-in-the-readme-live-app-url-after-the-cloud-deploy)

## Next — this quarter

Analytics capability that builds directly on already-shipped foundations, plus a
short list of reliability/quality fixes.

- **Cross-source correlations.** The weather and calendar *loaders* already run in
  `weekly_load`; the open work is the analysis layer — `mart_daily_context` +
  correlation columns ("did 5 back-to-back meetings tank my HRV?", "does recovery
  drop on hot nights?") surfaced on the Correlations page.
  → [BACKLOG: Cross-source enrichment](BACKLOG.md#feature-cross-source-enrichment--weather-calendar-density-sleep-environment)
- **Forecasting refinement.** Tune Holt's α/β per metric via walk-forward grid
  search, and add the 4th signal (sleep duration) to the forecast bands.
  → [BACKLOG: Fit Holt's hyperparameters](BACKLOG.md#improvement-fit-holts-hyperparameters-per-metric-via-grid-search)
  · [BACKLOG: Add sleep-duration to mart_forecast_bands](BACKLOG.md#improvement-add-sleep-duration-time-series-to-mart_forecast_bands)
- **Natural-language → SQL page (`13_query`).** Power-user companion to the
  conversational Ask agent: type a SQL-shaped request, get the query + result +
  refine loop, with read-only / `analytics_marts`-only guardrails.
  → [BACKLOG: Natural-language → SQL agent](BACKLOG.md#feature-natural-language--sql-agent-over-the-marts)
- **Sleep-target calibration.** Once N ≥ 60 nights, decide deliberately whether
  the sleep-score targets stay literature-derived or move to a personal baseline.
  → [BACKLOG: Calibrate sleep score targets](BACKLOG.md#refactor-calibrate-sleep-score-targets-to-personal-baseline)
- **Reliability & quality fixes.**
  - Header-only category CSVs not registering in `raw.file_inventory` (ledger gap).
    → [BACKLOG](BACKLOG.md#bug-header-only-category-csvs-dont-register-in-rawfile_inventory)
  - Integration test for the transaction-abort idempotency guarantee (the one
    untested leg of the idempotency contract).
    → [BACKLOG](BACKLOG.md#improvement-integration-test-for-transaction-abort-idempotency-consistency)
  - Extend mypy coverage from `ingest/` to `app/`.
    → [BACKLOG](BACKLOG.md#improvement-extend-mypy-coverage-to-app)

## Later — parking lot (scoped, not scheduled)

High-upside bets that turn the pipeline from a logging/analytics tool into an
insight engine. Each is a deliberate "someday," not a commitment.

- **Personal experiments framework** — log interventions, measure pre/post effect
  on RHR/HRV/sleep (personal causal inference).
  → [BACKLOG](BACKLOG.md#feature-personal-experiments-framework--log-interventions-measure-prepost-effect)
- **Auto-generated "Year in Review" report** — quarterly/annual narrative,
  Claude-written over the marts.
  → [BACKLOG](BACKLOG.md#feature-auto-generated-year-in-review-report--quarterly--annual-narrative)
- **dbt Mesh spike** — split into `health-core` + `analytics-derived` with
  cross-project refs (a senior-AE architecture exercise).
  → [BACKLOG](BACKLOG.md#exploration-dbt-mesh--split-into-health-core--analytics-derived-projects-with-cross-project-refs)
- **Semantic memory layer** — `pgvector` over journal + marts for long-horizon
  RAG ("when was the last time I felt this bad?").
  → [BACKLOG](BACKLOG.md#exploration-semantic-memory-layer--vector-store-over-journal--marts-for-long-horizon-rag)
- **RHR-baseline drift snapshot** — dbt SCD-2 snapshot for "today vs. this
  month's baseline."
  → [BACKLOG](BACKLOG.md#exploration-dbt-snapshot-for-resting-hr-baseline-drift)
- **`weekly-workout-planner` wiring** — once that skill exists, feed the day's
  planned session into `daily-workout-coach` for plan-vs-actual framing.
  → [BACKLOG](BACKLOG.md#improvement-wire-daily-workout-coach-to-read-the-weekly-plan-from-weekly-workout-planner)

---

## Recently shipped

See [`CHANGELOG.md`](CHANGELOG.md) for the full release history. Highlights through
`v0.3.0`: the forecasting marts (Holt's method, pure-SQL), the anomaly →
notification pipeline, the sleep hypnogram + composite-score marts, the
conversational Ask agent, the `daily-workout-coach` second consumer of
`mart_recovery_state`, self-hosted Prefect automation, the Tempo Firestore feed,
and the full Tier-1/Tier-2 docs set.
