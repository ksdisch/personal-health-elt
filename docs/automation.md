# Automation — scheduled weekly refresh

The weekly data refresh runs as a **self-hosted Prefect deployment** of the
existing `ingest.flows.weekly_load` flow. This page covers how to start it, the
schedule, how to fire a manual run, and the known tradeoff.

## Why self-hosted (and not GitHub Actions / launchd)

The deciding factor is **data locality**: the source Apple Health CSVs live on
this machine (Health Auto Export drops them into `data/raw/`). A self-hosted
Prefect worker runs where the files already are, so there is zero data-egress
step and no health data committed to the repo or lifted into object storage.

Prefect (over a raw `cron`/launchd shell job) buys a real schedule **plus**
retries and run observability — not a fire-and-forget script.

Cloud-native is deferred, not abandoned. The flow code is portable: once the
source CSVs are cloud-resident, the same `weekly_load` can be `prefect deploy`'d
to a process work pool or Prefect Cloud with no flow-code changes.

## Mechanism: `flow.serve()`

We use `flow.serve()` (Prefect 3.x), not a separate server + work pool +
worker. For a single personal flow, `serve()` is one long-lived foreground
process that *both* registers the `weekly-health-load` deployment (with its
cron) *and* executes its scheduled runs in-process. A work-pool/worker setup
would add a Prefect server, a work pool, and a separate worker process —
decoupling "deploy" from "execute" for no benefit on one laptop-bound flow.

## What the flow does each run

`weekly_load` is the **whole** refresh, end-to-end — not just extract+load:

1. **Load** — walk `data/raw/` and dispatch every new Health Auto Export CSV
   through the batch loaders (quantities, categories, workouts).
2. **Enrich** — backfill trailing weather + calendar density (both non-fatal:
   a bad API key or outage logs a warning and never blocks the build).
3. **Transform** — run `dbt build` against the **real** Postgres (your
   `transform/profiles.yml`), rebuilding the marts including
   `mart_recovery_state`. Skipped only if no new rows landed anywhere.
4. **Notify** — evaluate the notification rules against the fresh mart and
   send anomaly pushes (deduped per day).

Idempotency means a re-run on an unchanged drop folder is a no-op: the file
ledger short-circuits already-loaded files and `ON CONFLICT DO NOTHING` drops
duplicate rows.

### Retries & logs

- Per-task retries: load (1×/30s), weather (1×/60s), calendar (1×/60s),
  `dbt build` (2×/60s), notify (1×/30s).
- Flow-level retry: `1×` after `120s` as a coarse safety net for transient
  infra failures that outlast the task delays. Safe because the flow is
  idempotent end-to-end.
- A failed `dbt build` logs the last 20 lines of dbt stderr at `ERROR` before
  raising, so the alert is actionable from the Prefect run logs without a full
  stack trace. Each run logs a per-kind load breakdown and a JSON summary.

## Schedule

**Sunday 06:00 `America/Chicago`** (cron `0 6 * * 0`).

Defined once as `_SCHEDULE_CRON` / `_SCHEDULE_TZ` in
`ingest/flows/weekly_load.py`. This rebuilds `mart_recovery_state` with an
~11.5h buffer before its Sunday-evening consumers — the `weekly-health-review`
skill (5:30 PM CT) and `weekly-workout-planner` (6:00 PM CT). It assumes Health
Auto Export drops the week's CSVs overnight; if you export manually on Sunday
morning, move the hour later.

## Prerequisites

The `serve` process needs the same environment a manual `dbt build` does:

- `transform/profiles.yml` exists and points at your **real** Postgres (it's
  gitignored — `cp transform/profiles.yml.example transform/profiles.yml`, then
  set it or the `POSTGRES_*` env vars it reads).
- The `POSTGRES_*` env vars (and any `OPENWEATHER_*` / `CALENDAR_ICS_URL` /
  `PUSHOVER_*` you use) are exported in the shell that launches `serve`.
- Docker Postgres is up (`docker compose up -d`).

## Start the scheduler

```bash
# Long-lived foreground process: creates the deployment AND runs the schedule.
uv run python -m ingest.flows.weekly_load --serve
```

Leave it running. To survive display sleep on macOS, wrap it:

```bash
caffeinate -is uv run python -m ingest.flows.weekly_load --serve
```

For survive-reboot durability, run the same command under a launchd
`LaunchAgent` (`~/Library/LaunchAgents/`) with `KeepAlive=true` and the working
directory set to the repo root. Press `Ctrl-C` to stop the foreground process.

## Trigger a manual run

Two ways:

```bash
# 1. One-shot, no scheduler needed — runs the flow once and exits.
uv run python -m ingest.flows.weekly_load

# 2. Against the registered deployment, while `--serve` is running elsewhere.
uv run prefect deployment run 'weekly-health-load/weekly-health-load'
```

The one-shot form is the simplest for an ad-hoc refresh after dropping a new
export. The deployment form is useful to exercise the scheduled path on demand.

## Known tradeoff

This is **laptop-bound**: the machine must be awake at 06:00 Sunday for the run
to fire. `caffeinate` covers display sleep; a missed week is self-healing
because the loaders are idempotent and the weather/calendar backfills look back
14 / 60 days, so the next run re-covers any gap.

The accepted next step (out of scope today) is cloud-native execution once the
source CSVs are cloud-resident — Prefect Cloud or a GitHub Actions cron running
the same `weekly_load`.
