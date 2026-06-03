# Runbook: `weekly_load` failed or missed run

- **Trigger:** The scheduled Sunday 06:00 CT `weekly-health-load` run failed,
  crashed, or never fired (laptop asleep) — or you dropped a new export and an
  ad-hoc run errored.
- **Severity:** Operational / **S2** (stale-but-correct marts; no external SLA).
  Escalates to **S1** only if real `raw.*` data was destroyed — see
  [Rollback](#rollback).
- **Owner:** Kyle Disch (solo).
- **Last verified:** 2026-06-03.
- **Related runbooks:** [`../automation.md`](../automation.md) (scheduling,
  launchd, export sync) · [`../DEPLOYMENT.md`](../DEPLOYMENT.md) (cold-start /
  cloud).

> **The one thing to remember:** re-running `weekly_load` is **always safe**. Every
> loader is idempotent (SHA file ledger + `ON CONFLICT DO NOTHING`, single
> transaction — see [ADR-0003](../adr/0003-two-level-idempotency.md)), `dbt build`
> is rerunnable, notifications dedup per day, and the Firestore push is a fresh
> overwrite. A re-run on an unchanged drop folder is a **no-op**, not a duplicate.
> When in doubt, just re-run it (step 2 below).

## Symptoms

There is **no push alert on flow failure today.** Pushover fires only on
recovery-state *anomalies*, and only *after* a successful `dbt build` — so a
failed or missed run sends **nothing**. You find out one of these ways, roughly
in order of likelihood:

- **Stale data in the app / freshness warning.** Streamlit pages show old dates,
  or `dbt source freshness` warns (>2 days) or errors (>7 days) on
  `raw.{quantities,categories,workouts}`. *This is the most likely real signal,
  especially for a missed run.*
- **Missed Sunday run — nothing failed.** The Mac was asleep at 06:00 Sunday, so
  the cron never fired. There is **no error anywhere** — just no new flow run and
  no fresh marts. (This is the common case, and the safest.)
- **Failed/crashed run in Prefect.** The Prefect UI (<http://127.0.0.1:4200>)
  shows the `weekly-health-load` run as `Failed`/`Crashed`, or
  `uv run prefect flow-run ls --limit 5` shows no recent run.
- **Error in the launchd logs.** `/tmp/health-weekly-load.err.log` (the runner) or
  `/tmp/prefect-server.err.log` (the scheduler) shows a dbt stderr tail or a crash.

## Pre-checks

- [ ] **Identify which case you're in:** a *failed* run (something errored) vs. a
      *missed* run (laptop asleep, nothing ran). Both are safe to re-run; the
      missed case needs no diagnosis at all — skip to step 2.
- [ ] **Environment:** this pipeline has a single local "prod" — Docker Postgres.
      There is no staging. Confirm Postgres is up: `docker compose ps`
      (start it with `docker compose up -d` if not).
- [ ] **Config present:** `transform/profiles.yml` exists and points at your real
      Postgres; `POSTGRES_*` (and any `OPENWEATHER_*` / `CALENDAR_ICS_URL` /
      `PUSHOVER_*`) are exported in this shell; `HEALTH_EXPORT_PATH` resolves to
      the synced export folder (else it falls back to `./data/raw`).
- [ ] **Confirm your real data is intact BEFORE re-running** (guards against the
      historic data-loss class — see [Rollback](#rollback)). This one-liner uses
      the same connection the flow does, however your `POSTGRES_*` env is wired:

      ```bash
      uv run python -c "from sqlalchemy import text; from ingest.db import get_engine; \
      print(get_engine().connect().execute(text('select count(*) from raw.file_inventory')).scalar())"
      ```

      It should print a **non-zero** count on a populated dev DB.

## Resolution

1. **Read the failure** (skip for a missed run — nothing failed). Find which task
   failed in the Prefect run logs, or in `/tmp/health-weekly-load.err.log`. The
   flow logs a per-kind / per-metric breakdown and, on a `dbt build` failure, the
   last 20 lines of dbt stderr at `ERROR`. Tasks, in run order:
   `load_drop_folder → load_weather → load_calendar → run_dbt_build →
   notify_state_changes → push_recovery_state_to_tempo`.

2. **Re-run it — the safe default.** One-shot CLI (no scheduler needed):

   ```bash
   uv run python -m ingest.flows.weekly_load
   ```

   Already-loaded files short-circuit via the file ledger; row-level overlaps are
   dropped by `ON CONFLICT`; `dbt build` rebuilds the marts (and is skipped only
   if genuinely zero new rows landed). For most failures and **every** missed run,
   this is the entire fix.

   *(Alternative, if `--serve` is running: exercise the scheduled path with*
   `uv run prefect deployment run 'weekly-health-load/weekly-health-load'`*.)*

3. **Branch by which task failed:**
   - **`run_dbt_build` (`DbtBuildError`)** — read the stderr tail. Most likely a
     model error or a contract test failing on real data the CI fixtures didn't
     cover (e.g. a new `recovery_signal` value, a `unique(day)` violation, an
     `accepted_values` miss). Fix the model/seed/data, then re-run step 2 — the
     loaders already landed their rows, so the re-run skips straight to the build.
   - **`load_drop_folder`** — a bad/corrupt CSV. The `errored_metric_types` log
     names the file + error type. Fix or remove the offending CSV and re-run;
     previously-loaded files are skipped. (A not-yet-downloaded iCloud `.zip` is
     already logged-and-skipped, not an error.)
   - **`load_weather` / `load_calendar` / `notify_state_changes` /
     `push_recovery_state_to_tempo`** — these are **non-fatal**: the flow logs a
     warning and continues, so they never block the build. No action required;
     re-running self-heals (weather backfills 14 days, calendar 60 days,
     notifications dedup per day, the Firestore push overwrites). Only chase these
     if you specifically want the enrichment/alert that was missed.
   - **Missed run (laptop asleep)** — nothing failed. Run step 2 now; the
     idempotent backfill covers the gap. To prevent recurrence, schedule a wake:
     `sudo pmset repeat wakeorpoweron Sun 05:55:00` (see
     [`../automation.md`](../automation.md)).

## Verification

- Flow summary logs `"dbt_exit_code": 0` (or `null` if there were truly no new
  rows anywhere — also a valid outcome).
- `uv run dbt source freshness --project-dir transform --profiles-dir transform`
  no longer errors; Streamlit pages show recent dates.
- `mart_recovery_state` has the expected latest `day` and its contract is green:
  `uv run dbt test --select mart_recovery_state --project-dir transform --profiles-dir transform`
  (`unique(day)` + `accepted_values(recovery_signal)`).
- Consumers reconcile: the `weekly-health-review` skill reads fresh state; the
  Tempo PWA `users/{uid}/recovery_state/latest` doc is updated (if enrolled); the
  `daily-workout-coach` sees the fresh row. (See
  [ADR-0005](../adr/0005-mart-recovery-state-public-api.md) for the contract.)
- `raw.file_inventory` count grew by the number of new files (or is unchanged on a
  pure re-run).

## Rollback

- **There is nothing to roll back for a re-run.** Idempotency means a re-run
  cannot corrupt or duplicate data. If a re-run fails the *same* way, it's
  deterministic — **stop, don't loop**; diagnose the dbt model or CSV (step 3).
- **The one genuinely destructive risk is not the flow** — it's
  `TRUNCATE raw.file_inventory CASCADE` (used by some test/cleanup paths). **Never
  run it against your real DB.** If real data was wiped (this happened once —
  286,770 rows; root-caused and fixed in `CHANGELOG.md` v0.3.0), recover by
  re-ingesting: point at the historical export and re-run —
  `HEALTH_EXPORT_PATH=./data/raw/export_full uv run python -m ingest.flows.weekly_load`
  (or unset `HEALTH_EXPORT_PATH` to reload from `./data/raw`). Then re-run the
  [Data-integrity verification](#verification) checks. Write it up with
  [`../postmortems/TEMPLATE.md`](../postmortems/TEMPLATE.md) as an **S1**.

## Prevention / follow-up

- **No flow-failure alert.** Pushover is anomaly-only; a terminal failure pushes
  nothing. *Follow-up:* add a terminal-failure notification hook so a failed/
  missed run is actively surfaced instead of discovered via stale data.
- **Missed Sunday runs.** `sudo pmset repeat wakeorpoweron Sun 05:55:00` so the
  Mac is awake at the cron time; a missed week self-heals regardless.
- **Freshness as an SLI.** `dbt source freshness` is already configured; formalize
  a "data ≤ 7 days fresh" SLO note (Tier-3) and check it as the canary.
- **Cloud-native execution.** The laptop-bound tradeoff is accepted for now; once
  the source CSVs are cloud-resident the same flow can run on Prefect Cloud / GHA
  with no code change (see [ADR-0004](../adr/0004-self-hosted-prefect-over-gha-launchd.md)
  and [`../automation.md`](../automation.md)).

## References

- **Flow source:** [`../../ingest/flows/weekly_load.py`](../../ingest/flows/weekly_load.py)
- **Automation / scheduling:** [`../automation.md`](../automation.md)
- **Cloud deploy / cold-start:** [`../DEPLOYMENT.md`](../DEPLOYMENT.md)
- **Related ADRs:** [0003 two-level idempotency](../adr/0003-two-level-idempotency.md) ·
  [0004 self-hosted Prefect](../adr/0004-self-hosted-prefect-over-gha-launchd.md) ·
  [0005 `mart_recovery_state` public API](../adr/0005-mart-recovery-state-public-api.md)
- **Incident write-ups:** [`../postmortems/`](../postmortems/) (use `TEMPLATE.md`)
- **Release history:** [`../../CHANGELOG.md`](../../CHANGELOG.md)
