# ADR-0004: Self-hosted Prefect (`flow.serve` under launchd) over GitHub Actions cron

- **Status:** Accepted
- **Date:** 2026-05-27
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0003 (idempotent loaders make re-runs safe), `ingest/flows/weekly_load.py`, `docs/automation.md`, `deploy/launchd/`

## Context

The weekly refresh needs to: read Apple Health CSVs that sync into a local iCloud
Drive folder, load them into a **local** Dockerized Postgres, run `dbt build`, and
feed three consumers. The data lives on the user's laptop. The scheduling question
is *where the job runs*, and the dominant constraint is **data locality** — the
CSVs and the warehouse are both local, so any cloud-based scheduler would need the
data shipped to it.

The relevant options were a hosted CI cron (GitHub Actions), a bare OS scheduler
(launchd/cron driving a script directly), or a self-hosted workflow engine
(Prefect 3.x `flow.serve()`).

## Decision

We run a self-hosted **Prefect** deployment via `weekly_load.serve(...)` with a
`Cron("0 6 * * 0", timezone="America/Chicago")` schedule — a single long-lived
foreground process that both registers the deployment and executes its scheduled
runs in-process (no separate Prefect server, work pool, or worker). It runs where
the data already is. macOS **launchd** plists in `deploy/` keep the `serve`
process alive and restart it; `caffeinate` mitigates sleep.

## Alternatives considered

- **GitHub Actions cron** — rejected: the runner has no access to the local iCloud
  CSVs or the local Postgres. Making it work would mean uploading health data to
  a cloud runner and provisioning a cloud database — a data-egress and
  privacy cost with no upside for a single-user local tool.
- **Bare launchd/cron running a Python script directly** — rejected: loses
  per-task retries, structured run logging, and the observable run history Prefect
  gives for free. The flow already needs retry semantics (dbt build, transient
  Postgres restarts) that we'd otherwise hand-roll.
- **A full Prefect server + worker + work pool** — rejected: operationally heavy
  for one weekly flow on one machine. `flow.serve()` collapses scheduler + worker
  into one process, which is the right size here.

## Consequences

**Positive:**
- No data egress: health data and warehouse never leave the laptop.
- Per-task retries, structured logs, and run history without extra infrastructure.
- launchd handles process lifecycle/restart; the schedule constants are the single
  source of truth shared by `_serve()` and the docs.

**Negative:**
- **Laptop-bound**: the machine must be awake at 06:00 CT Sunday for the run to
  fire. This is an accepted, documented tradeoff (mitigated by `caffeinate`/launchd,
  and made safe by ADR-0003 — a missed run is recovered by simply re-running, which
  is a no-op for already-loaded data).
- Single point of failure (one laptop); no HA. Acceptable for a personal tool.

**Neutral but worth noting:**
- `docs/DEPLOYMENT.md` separately covers a cloud deploy path (managed Postgres +
  Streamlit Cloud) for the *app*; that is orthogonal to *ingest* scheduling, which
  this ADR governs.

## References

- `ingest/flows/weekly_load.py` — `_serve()`, the cron constants, retry config.
- `docs/automation.md` — schedule rationale, launchd setup, the sleep caveat.
- CLAUDE.md → "Scheduled refresh".
