# Orchestrator — implement the categories loader (BACKLOG Feature 1)

You are the **orchestrator** for shipping the HK categories loader in
`personal-health-elt`. Paste this prompt as the first message of a fresh
Claude Code session.

## Scope: what "ship" means

`ingest/loaders/categories.py:13` is a `NotImplementedError` stub. Six HK
category types — `SleepAnalysis`, `MindfulSession`, `AudioExposureEvent`,
`HighHeartRateEvent`, `LowHeartRateEvent`, `AppleStandHour` — are exported
by Health Auto Export but skipped at ingest. The deliverable is a working
loader that lands rows in `raw.categories` with the same two-level
idempotency contract as quantities/workouts (SHA file ledger + ON CONFLICT
row dedup, single transaction), is dispatched by `ingest/loaders/batch.py`,
and is observable in the warehouse after a real export.

**This is loader-only.** No `stg_categories.sql`, no marts, no Streamlit.
Staging and downstream consumers are explicitly out of scope and tracked
as a follow-up in `BACKLOG.md`.

**Artifacts to ship:**

- `scripts/init_raw_schema.sql` — append `raw.categories` DDL after the
  workouts block
- `ingest/loaders/categories.py` — implement `parse_categories_csv` and
  `load_categories_csv` (replace the stub)
- `ingest/loaders/batch.py` — import + register the new loader (dispatch
  already returns `"categories"` for `HKCategoryTypeIdentifier*` files)
- `tests/test_categories_loader.py` — new file, parser-only unit tests

## Your role: coordinate only

You **do not write code, edit files, or run shell commands yourself.** Every
concrete step is dispatched to a fresh subagent via the **Agent tool** (also
referred to as the Task tool). If you reach for Read, Edit, Write, or Bash
directly — STOP. Dispatch a worker instead.

Fill in `.claude/templates/phase-brief.md` for every dispatch and pass it
as the worker's prompt verbatim.

## Subagents (defined in `.claude/agents/`)

| Subagent | Role | When |
|---|---|---|
| `loader-engineer` | Idempotent loaders in `ingest/`. Knows two-level idempotency contract. | Phase A (build), Phase B (real-export verify) |
| `verifier` | Read-only. Runs full project gate, reports structured pass/fail. | Phase C |
| `dbt-modeler` | Writes/edits dbt SQL + schema.yml. | Reserved — not used this task. |
| `streamlit-page-wright` | Edits `app/pages/*` + `app/lib/queries.py`. | Reserved — not used this task. |

Dispatch with `Agent(subagent_type="<name>", ...)`.

## Hand-off style: single session, sequential

Phases run sequentially (A → B → C → D). Within a phase there is a single
dispatch (the work doesn't fan out into independent sub-tasks).

---

## Phase A — Build & unit-test the loader

**Goal.** Implement `load_categories_csv` end-to-end, add the
`raw.categories` DDL, register the loader in the batch dispatcher, and write
parser-only unit tests. No Postgres connection needed for this phase.

**In scope (worker MAY read AND edit):**
- `scripts/init_raw_schema.sql` (append after the workouts block at line 77)
- `ingest/loaders/categories.py` (replace the stub)
- `ingest/loaders/batch.py` (extend the `loaders` dict + add the import)
- `tests/test_categories_loader.py` (new file)

**Out of scope (FORBIDDEN to touch):**
- `ingest/loaders/quantities.py`, `ingest/loaders/workouts.py` — no refactor;
  helpers stay duplicated this session (BACKLOG flags extraction as a
  separate item)
- `transform/models/**` — no staging or marts edits
- `transform/models/marts/mart_recovery_state.sql` — public API
- `app/**` — Streamlit untouched
- `transform/models/sources.yml` — already declares `categories` at line 10

**Implementation reference (mirrors quantities.py exactly):**

DDL to append to `scripts/init_raw_schema.sql`:

```sql
-- Categories: HKCategoryTypeIdentifier* events (sleep stages, mindful
-- sessions, audio events, AppleStandHour, HR threshold events). Optional
-- per-type metadata (HKTimeZone on sleep rows, HKHeartRateEventThreshold
-- on HR events) lands in nullable TEXT columns.
-- Natural key: (category_type, source_name, start_ts).
CREATE TABLE IF NOT EXISTS raw.categories (
    category_type           TEXT NOT NULL,
    category_value          TEXT,
    source_name             TEXT,
    source_version          TEXT,
    product_type            TEXT,
    device                  TEXT,
    start_ts                TIMESTAMPTZ NOT NULL,
    end_ts                  TIMESTAMPTZ,
    hk_time_zone            TEXT,
    hk_heart_rate_threshold TEXT,
    source_file             TEXT NOT NULL,
    source_sha256           TEXT NOT NULL REFERENCES raw.file_inventory(sha256),
    loaded_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (category_type, source_name, start_ts)
);

CREATE INDEX IF NOT EXISTS categories_type_time_idx
    ON raw.categories (category_type, start_ts);

COMMENT ON TABLE raw.categories IS
    'Raw HealthKit category samples. Loaders upsert via ON CONFLICT on the natural key.';
```

Loader structure (parallel to `ingest/loaders/quantities.py`):

- `_HK_TO_SNAKE` maps `type → category_type`, `value → category_value`,
  `sourceName → source_name`, `sourceVersion → source_version`,
  `productType → product_type`, `device`, `startDate → start_ts`,
  `endDate → end_ts`, `HKTimeZone → hk_time_zone`,
  `HKHeartRateEventThreshold → hk_heart_rate_threshold`.
- Required columns (post-rename) are the common six; the two optional
  metadata columns are added as NaN if missing (mirroring
  `workouts.py:119-121`).
- `parse_categories_csv(path)` strips the optional `sep=,` Excel hint,
  renames per the map, parses `start_ts` / `end_ts` as UTC-aware pandas
  timestamps, raises `ValueError` on missing required columns.
- `load_categories_csv(path: Path, engine: Engine | None = None) -> LoadResult`
  — fast-path SHA check outside the transaction; inside `engine.begin()`
  it records the file ledger then upserts. ON CONFLICT
  `index_elements=["category_type", "source_name", "start_ts"]`.
- Module-local helpers (copies from quantities.py): `_already_loaded`,
  `_record_file`, `_upsert_rows`, `_records_with_none_for_nan`.

Batch registration:

- `ingest/loaders/batch.py:24` — add
  `from ingest.loaders.categories import load_categories_csv`.
- `ingest/loaders/batch.py:80` — extend the `loaders` dict to include
  `"categories": categories_loader` using the same injectable-parameter
  pattern as quantities/workouts.

Tests (parser-only, no DB — mirrors `tests/test_quantities_loader.py`):

1. Sleep stage row → `category_type="SleepAnalysis"`,
   `category_value="asleepCore"`, `end_ts > start_ts`.
2. Mindful session row → `value="notApplicable"`, has duration.
3. `HighHeartRateEvent` row → `hk_heart_rate_threshold` literal preserved
   (e.g., `"120 count/min"`).
4. `AppleStandHour` row → `category_value="stood"`, point-in-time.
5. Missing optional columns → values land as `None`, parse succeeds.
6. Missing required column → raises `ValueError`.
7. `sep=,` Excel hint stripped.
8. Empty file (header only) → empty DataFrame, no exception.

**Success criteria:**
- `uv run ruff check ingest/loaders/categories.py ingest/loaders/batch.py tests/test_categories_loader.py` exits 0
- `uv run pytest tests/test_categories_loader.py` green
- `uv run pytest tests/test_batch_loader.py` still green (categories now
  dispatches; the existing test at `tests/test_batch_loader.py:14-15`
  already expects this)
- `mart_recovery_state.sql` byte-identical to its pre-phase state

---

## Phase B — Real-export verification

**Goal.** Apply the DDL, ingest the local export against the running
Postgres instance, and confirm the idempotency contract — re-running the
flow must add zero rows.

**Worker:** `loader-engineer` (second dispatch — fresh context, same agent).

**No file edits.** This phase is execution + observation only.

**Commands:**
```bash
docker exec -i health_postgres psql -U health -d health \
  < scripts/init_raw_schema.sql
uv run python -m ingest.flows.weekly_load
docker exec health_postgres psql -U health -d health -c \
  "SELECT category_type, COUNT(*) FROM raw.categories GROUP BY 1 ORDER BY 1;"
uv run python -m ingest.flows.weekly_load        # second run — idempotency check
docker exec health_postgres psql -U health -d health -c \
  "SELECT COUNT(*) FROM raw.categories;"
```

**Success criteria:**
- Non-zero rows for the four populated types in `data/raw/export_full/`:
  `SleepAnalysis` (~832), `MindfulSession` (~7), `HighHeartRateEvent` (~3),
  `AppleStandHour` (~706). Zero rows for `AudioExposureEvent` and
  `LowHeartRateEvent` is acceptable (source CSVs are header-only).
- `raw.file_inventory` gains one row per category CSV ingested.
- Second flow run reports `LoadResult(skipped=True)` for each category
  file, and the `raw.categories` row count after the second run matches
  the count after the first run exactly. **Hard gate.**

---

## Phase C — Full project gate (regression check)

**Goal.** Confirm no existing model, test, or lint regressed.

**Worker:** `verifier` (read-only).

```
uv run ruff check .
uv run pytest
uv run dbt parse --project-dir transform --profiles-dir transform
uv run dbt build  --project-dir transform --profiles-dir transform
```

**Success criteria:** all four exit 0. Verifier returns the structured
`OVERALL: PASS / FAIL` summary defined in `.claude/agents/verifier.md`.

**On failure:** dispatch `loader-engineer` with a targeted fix brief, then
re-dispatch `verifier`. Two-fix limit — pause for user input on the third
attempt. No silent test loosening.

---

## Phase D — Commit on the feature branch

**Goal.** Land changes on `feat/categories-loader` with a scoped commit and
open a PR.

**Worker:** dispatch `loader-engineer` (it's the agent closest to the
changed files; the brief stays scoped to staging-by-name + commit + push).

1. Confirm current branch is `feat/categories-loader`. If `main`, pause for
   the user.
2. Stage the deliberately-named files (NEVER `git add -A` or `git add .`):
   ```
   git add ingest/loaders/categories.py ingest/loaders/batch.py \
           scripts/init_raw_schema.sql tests/test_categories_loader.py \
           .claude/orchestrator-prompt.md
   ```
3. Commit with a HEREDOC titled
   `feat: implement HK categories loader (BACKLOG Feature 1)`, listing the
   six category types and the idempotency contract in the body.
4. `git status` and `git log -1 --stat` to confirm.
5. **Push the feature branch.** Pre-authorized for THIS session ONLY for
   `feat/categories-loader`. Force-push, merge to `main`, and any direct
   push to `main` remain forbidden.
   ```
   git push -u origin feat/categories-loader
   ```
6. Open a PR via `gh pr create` (HEREDOC body for formatting):
   ```
   gh pr create --title "feat: implement HK categories loader (BACKLOG Feature 1)" \
     --body "$(cat <<'EOF'
   ## Summary
   - New loader `ingest/loaders/categories.py` ingesting the six HK category
     types (SleepAnalysis, MindfulSession, AudioExposureEvent,
     HighHeartRateEvent, LowHeartRateEvent, AppleStandHour) into
     `raw.categories`
   - Two-level idempotency: SHA file ledger + ON CONFLICT row dedup in a
     single transaction
   - `raw.categories` DDL added to `scripts/init_raw_schema.sql`
   - Registered in `ingest/loaders/batch.py` (dispatcher already recognized
     `HKCategoryTypeIdentifier*`)
   - Parser unit tests cover all six types + edge cases

   ## Test plan
   - [x] ruff check clean
   - [x] pytest tests/test_categories_loader.py green
   - [x] dbt parse + dbt build clean
   - [x] Real export ingested; row counts non-zero for populated types
   - [x] Re-run is a no-op (zero new rows, file ledger unchanged)

   Follow-up (separate BACKLOG entries): extract `_already_loaded` /
   `_record_file` to a shared helper; add `stg_categories.sql`.

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```
7. Report the PR URL back to the user.

**End state.** Phase D completes when the PR is open and its URL has been
reported.

---

## Inter-phase summary format

After each phase, output exactly:

```
PHASE <letter> — <name>
DONE: <one sentence>
CHANGED FILES: <list, or "none">
TESTS: <pass>/<total> passed
IDEMPOTENCY CHECK: <Phase B only: fresh rows / reload rows added — expect reload = 0>
OPEN QUESTIONS: <bulleted, or "none">
NEXT RECOMMENDATION: <next phase, or "pause for user">
```

## When to pause autonomously

**Proceed without asking when:**
- A phase's success criteria are met
- No file outside the phase's in-scope list needs changing
- Workers report no OPEN QUESTIONS

**Pause and ask the user when:**
- A worker hits an error it can't fix in two attempts
- A change set would touch `mart_recovery_state.sql`,
  `ingest/loaders/quantities.py`, or `ingest/loaders/workouts.py`
- A worker proposes editing `CLAUDE.md` or this orchestrator prompt
- About to force-push, merge to `main`, or push to `main` directly
  (push of `feat/categories-loader` is pre-authorized — see Phase D)
- About to run `git add -A` / `git add .` / `rm -rf` / `dbt run-operation`
- Phase B's idempotency check fails (this is a hard contract violation,
  not a recoverable test failure)

## Hard rules (also enforced in CLAUDE.md)

- `uv` only. Never raw `pip install`.
- Two-level idempotency is non-negotiable: SHA ledger + ON CONFLICT inside
  a single `engine.begin()`.
- `raw.categories` natural key is `(category_type, source_name, start_ts)`.
  This matches the quantities/workouts convention and must not drift.
- Timezones: loaders land timestamps as UTC. TZ conversion happens in
  staging (out of scope this session, but the contract still holds).
- `mart_recovery_state.sql` is a versioned public API. Off-limits.
- Quantities and workouts loaders are off-limits. Helper duplication is
  intentional this session.
- Branches: `feat/`, `fix/`, `refactor/`, `docs/`. Never commit to `main`.
- Stage files by name. Never `git add -A` or `git add .`.
- `git push -u origin feat/categories-loader` is pre-authorized for THIS
  session. Force-push, merge into `main`, and any direct push to `main`
  remain forbidden without further user approval.
