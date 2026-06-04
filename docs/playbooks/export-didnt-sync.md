# Playbook: export didn't sync from iCloud

- **Scenario:** The marts have gone stale and you suspect this week's Apple Health
  export never reached the drop folder — so `weekly_load` had nothing new to load.
- **Severity:** Operational / S2 (stale-but-correct data; self-healing).
- **Owner:** Kyle Disch (solo).
- **Last verified:** 2026-06-04.
- **Related:** [`../automation.md`](../automation.md) (the full export → iCloud → load
  mechanism) · [flow-failure runbook](../runbooks/weekly-load-failure.md) ·
  [freshness SLO](../reliability/slos.md).

> **Why this is its own scenario:** the export *tap* is **manual** — the Simple Health
> Export CSV app has no scheduler, so the only un-automatable step is you tapping
> "export." Everything after (iCloud sync, zip extraction, load, build) is automatic.
> When data stops flowing, the cause is almost always *upstream of the loader*: no new
> file in the drop folder. Nothing errors — the run just loads zero rows and skips the
> build. The flow-failure runbook covers *failures*; this covers *silence*.

## Symptoms

- `dbt source freshness` warns/errors; Streamlit pages show old dates.
- The `weekly_load` summary logs `"files_loaded": 0` and
  `"No new rows (HK, weather, or calendar); skipping dbt build"`.
- The drop folder has no new dated CSV/zip — or shows a `.icloud` placeholder (a
  dataless stub iCloud hasn't downloaded yet).

## Diagnose

1. **Find the resolved drop path** (it's `HEALTH_EXPORT_PATH`, else `./data/raw`):

   ```bash
   uv run python -c "from ingest.config import RAW_DATA_PATH; print(RAW_DATA_PATH)"
   ```

2. **List it and look for new / undownloaded files:**

   ```bash
   ls -la "$HEALTH_EXPORT_PATH"
   find "$HEALTH_EXPORT_PATH" -name '*.icloud'   # any match = not yet downloaded
   ```

   - New dated `*_SimpleHealthExportCSV.csv` / `.zip` present → not a sync problem;
     re-run the flow (it may simply not have run — see the flow-failure runbook).
   - `.icloud` placeholder(s) → iCloud hasn't pulled the file down yet (cause **B**).
   - Nothing new at all → the export was never tapped (cause **A**) or the path is
     wrong (cause **D**).

## Resolve

Pick by cause; **every path ends in an idempotent re-run**, so you can't make it worse.

- **A — export was never tapped.** On the phone: open *Simple Health Export CSV* →
  export → share sheet → **Save to Files → iCloud Drive → `HealthExports`**. Wait for
  it to sync to the Mac, then:

  ```bash
  just load            # or: uv run python -m ingest.flows.weekly_load
  ```

- **B — file is a `.icloud` placeholder.** Force the download, then re-run:

  ```bash
  open "$HEALTH_EXPORT_PATH"          # then double-click the file in Finder to pull it
  # or, scripted:
  brctl download "$HEALTH_EXPORT_PATH/<filename>"
  find "$HEALTH_EXPORT_PATH" -name '*.icloud'   # should now be empty
  just load
  ```

- **C — zip present but no CSVs loaded.** The batch loader auto-extracts `*.zip` into a
  sibling dir before walking for CSVs, and skips a not-yet-downloaded archive
  (cause B). Confirm the zip is fully downloaded (no `.icloud`), then re-run `just load`
  — extraction is idempotent.

- **D — wrong / unset path.** Fix `HEALTH_EXPORT_PATH` in `.env` to point at the synced
  folder, **or** drop the export straight into `./data/raw` over USB/AirDrop and unset
  `HEALTH_EXPORT_PATH` (it falls back to `./data/raw`). Then `just load`.

## Verify

- The flow summary now shows `files_loaded > 0` / `rows_inserted > 0` (or a deliberate
  no-op if you re-ran without truly-new data — also fine; the ledger dedups).
- `just freshness` (`dbt source freshness`) is green.
- Streamlit shows the new most-recent date; `mart_recovery_state` has the expected
  latest `day`.

## Prevent

- Export each **Sunday morning before 06:00 CT** (ahead of the scheduled run), and keep
  the Mac online so iCloud has time to sync the file down.
- A genuinely missed week **self-heals**: the loaders are idempotent and the
  weather/calendar backfills look back 14 / 60 days, so the next run re-covers the gap.
- **Do not** switch export apps casually — the loaders are coded to this app's exact
  CSV schema; a different exporter needs a new loader (see [`../automation.md`](../automation.md)).
