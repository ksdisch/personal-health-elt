# Automation — scheduled weekly refresh

The weekly data refresh runs as a **self-hosted Prefect deployment** of the
existing `ingest.flows.weekly_load` flow. This page covers how to start it, the
schedule, how to fire a manual run, and the known tradeoff.

## Why self-hosted (and not GitHub Actions / launchd)

The deciding factor is **data locality**: the source Apple Health CSVs live on
this machine (the drop folder — see "Automating the export" below). A
self-hosted Prefect worker runs where the files already are, so there is zero
data-egress step for the pipeline and no health data committed to the repo or
lifted into object storage.

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

1. **Load** — walk the drop folder (`HEALTH_EXPORT_PATH`, default `data/raw/`)
   and dispatch every new CSV through the batch loaders (quantities,
   categories, workouts).
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
skill (5:30 PM CT) and `weekly-workout-planner` (6:00 PM CT). It assumes the
week's CSVs have synced in overnight; if you run the export manually on Sunday
morning, move the hour later.

## Automating the export (where the CSVs come from)

The source CSVs are produced on the iPhone by the **Simple Health Export CSV**
app (filenames look like `..._SimpleHealthExportCSV.csv`). The loaders are coded
to that app's exact schema: a leading `sep=,` Excel hint, then columns
`type, sourceName, sourceVersion, productType, device, startDate, endDate,
unit, value`. A *different* exporter (e.g. Health Auto Export) produces a
different CSV layout and would need a new loader — see the BACKLOG before
switching apps.

That app is **manual / on-demand only** — it exports through the iOS share
sheet and has no built-in scheduler. So the export *tap* cannot be fully
automated; what we automate is everything after it:

1. **On the phone** — open Simple Health Export CSV, export (All / the metrics
   you want), and in the share sheet choose **Save to Files → iCloud Drive →
   `HealthExports`**. (One-time: create that folder the first time.) ~20s,
   ideally each Sunday morning before the 06:00 run, or any cadence — a missed
   week self-heals via idempotency. An "Export All" arrives as a single `.zip`;
   leave it as-is — see step 3.
2. **On the Mac** — iCloud Drive syncs that folder down automatically. The
   pipeline reads it directly via `HEALTH_EXPORT_PATH` in `.env`:
   ```bash
   HEALTH_EXPORT_PATH="/Users/<you>/Library/Mobile Documents/com~apple~CloudDocs/HealthExports"
   ```
   Already set on this machine. The Sunday `weekly_load` then walks that folder
   (recursively, idempotent) and loads anything new.
3. **Zips are auto-extracted** — the batch loader's `extract_new_zips` expands
   any `*.zip` in the drop folder into a sibling dir (named after the archive
   stem) before walking for CSVs, since the recursive `*.csv` walk never looks
   inside an archive. It's idempotent (skips a zip already extracted) and
   non-fatal (a corrupt / not-yet-downloaded archive is logged and skipped). So
   you never unzip by hand — dropping the `.zip` is enough.

**Why `HEALTH_EXPORT_PATH` and not a symlink:** a `data/raw/icloud` symlink was
tried and rejected — Python 3.12's `Path.rglob("*.csv")` does **not** follow a
symlink encountered mid-walk, so the synced files were invisible to the loader.
Pointing the env var at the iCloud folder makes it the real walk root, which
`rglob` handles correctly.

**Tradeoff to know:** this routes health CSVs through *your* iCloud Drive (your
personal cloud, same trust boundary as iCloud Health sync) rather than keeping
them strictly on-disk. It does not affect the pipeline's "no egress / nothing in
the repo" property — compute stays local and `data/raw/*` is gitignored. If you
prefer zero cloud, drop exports straight into `./data/raw` over USB/AirDrop and
unset `HEALTH_EXPORT_PATH`.

**Historical data:** your existing April export lives in `./data/raw/export_full`
and is already loaded in Postgres, so it's untouched by this switch. Only *new*
exports flow through iCloud. If you ever rebuild the DB from scratch, either
also copy `export_full` into the iCloud folder or temporarily unset
`HEALTH_EXPORT_PATH` to reload from `./data/raw`.

## Prerequisites

The `serve` process needs the same environment a manual `dbt build` does:

- `transform/profiles.yml` exists and points at your **real** Postgres (it's
  gitignored — `cp transform/profiles.yml.example transform/profiles.yml`, then
  set it or the `POSTGRES_*` env vars it reads).
- The `POSTGRES_*` env vars (and any `OPENWEATHER_*` / `CALENDAR_ICS_URL` /
  `PUSHOVER_*` you use) are exported in the shell that launches `serve`.
- Docker Postgres is up (`docker compose up -d`).
- `HEALTH_EXPORT_PATH` resolves to the synced export folder (see "Automating
  the export"); unset, it falls back to `./data/raw`.

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
