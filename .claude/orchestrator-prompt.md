# Orchestrator — personal-health-elt

This file governs every session that touches this repo, regardless of how it
runs. §1–§2 are invariants that always apply. §3 describes two operating
modes. §4 resolves conflicts between them.

---

## §1 Invariants

Rules that hold in every mode, every session, no exceptions.

### Environment
- `uv` only. Never `pip install` directly — always `uv add` / `uv sync` / `uv run`.

### Idempotency contract
All loaders MUST be safe to re-run on the same file. Two levels, both
inside `engine.begin()`:

1. **File-level: SHA256 ledger** — hash the file; if `raw.file_inventory`
   already has that hash, skip entirely.
2. **Row-level: ON CONFLICT** — upsert on the natural key:
   - quantities: `(metric_type, source_name, start_ts)`
   - workouts: `(activity_type, start_ts, source_name)`
   - categories: `(category_type, source_name, start_ts)`

   A failed insert MUST roll back the `file_inventory` entry so the next
   run reprocesses cleanly.

### `mart_recovery_state` is a versioned public API
This mart has **two downstream consumers**: the `weekly-health-review`
Claude skill (Markdown briefing path) and the Tempo PWA's Rhythm view
(Firestore feed). Schema changes — renaming a column, dropping a field,
changing a unit, adding or removing `recovery_signal` values — require
updating **both** consumers in lockstep. The `accepted_values` test on
`recovery_signal` and the `unique(day)` test in
`transform/models/marts/schema.yml` are the durable contract surface.
**Off-limits without an explicit contract-change authorization.**

### Timezone handling
Loaders land timestamps as UTC. TZ normalization (`America/Chicago`)
happens in staging only — never in intermediate or marts.

### dbt layering
`staging → intermediate → marts`. Marts MUST NOT `source()` directly.
Intermediate is never a final consumer. Materializations: staging = view,
intermediate = view, marts = table. HR zones are always `ref('hr_zones')`;
never hardcode 136–153 bpm.

### Git
- Branch naming: `feat/`, `fix/`, `refactor/`, `docs/`. Never commit to `main`.
- Stage files by name. Never `git add -A` or `git add .`.
- Force-push, merge to main, and push to main all require explicit
  per-session user authorization. A standing pre-approval is not sufficient.
- Every non-trivial architectural decision should be captured in an ADR
  under `docs/adr/` if not already documented.

---

## §2 Gates

### Blast-radius tiers

| Tier | Scope | Gate |
|------|-------|------|
| **T1** | `mart_recovery_state.sql`, its schema contract (column rename/drop, unit change, `recovery_signal` value list) | **Hard stop.** Both downstream consumers must be updated in lockstep. Explicit user authorization required in every mode, every session. |
| **T2** | `ingest/loaders/quantities.py`, `ingest/loaders/workouts.py`, natural keys in `scripts/init_raw_schema.sql` | **Pause before proceeding.** Idempotency regressions are silent in unit tests. Verify with a real-export round-trip after any change here. |
| **T3** | `ingest/loaders/batch.py` (dispatch table), `CLAUDE.md`, this file | **Surface before editing.** These are project-wide contracts; a change has repo-wide blast radius. |
| **T4** | New ingest loaders, staging views, intermediate views, app pages | Proceed per-mode rules in §3. |

### Manual-smoke → draft-PR gate
Any T1–T3 change, and any new loader that will run against real data, must:

1. Pass the full project gate: `ruff check`, `pytest`, `dbt parse`, `dbt build`.
2. Demonstrate idempotency: run the flow twice; row count after run 2 MUST
   equal row count after run 1. A mismatch is a hard contract violation —
   do NOT retry; stop and surface immediately.
3. Open as a **draft PR** until both criteria above are confirmed in the
   PR description.

### Two-fix rule
If a fix fails twice on the same check: STOP, return OPEN QUESTIONS
describing what was tried and what blocked progress. Do not loosen tests,
disable hooks, or skip CI. Do not run `git add -A`, `rm -rf`, or
`dbt run-operation` for cleanups without explicit authorization.

---

## §3 Operating modes

### §3.1 Autonomous mode (default)

A single session plans, builds, tests, verifies the §2 gates, and opens
a PR. No mandatory human checkpoints during execution.

**Workflow:**
1. Read the scope (BACKLOG item, user brief, or filled-in phase brief).
2. Plan the implementation — consult §1 and §2 before touching any file.
3. Implement directly: write code, edit SQL, run tests, verify locally —
   all with available tools. No worker dispatch required.
4. Self-check §2 gates before staging anything.
5. Stage named files, commit on a feature branch, open a PR (or draft PR
   per the smoke gate).
6. Stop and surface to the user when:
   - A T1 gate would be triggered (mart contract change).
   - The two-fix rule fires and the issue is still unresolved.
   - A required change is outside the stated scope.
   - About to push to main, force-push, or merge.
   - The idempotency check (run-2 = 0 new rows) fails.

**Specialist agents as an on-demand toolbox (not a mandatory pipeline):**
The four specialists under `.claude/agents/` can be invoked at any point
via `Agent(subagent_type="<name>", ...)` when context isolation or parallel
work is useful. They are NOT a required assembly line in autonomous mode.

| Agent | When useful |
|-------|-------------|
| `loader-engineer` | Complex loader refactors, idempotency verification |
| `verifier` | Independent regression check before commit |
| `dbt-modeler` | Multi-model dbt changes where a fresh context helps |
| `streamlit-page-wright` | New app pages or shared-query surgery |

### §3.2 High-oversight dispatch mode (optional)

The original pipeline model. Use when you want explicit human approval at
each phase boundary, or when coordinating a large change across multiple
repo areas where human review between phases is the right call.

**The session role in this mode:**
- Orchestrator only: reads scope, fills in `.claude/templates/phase-brief.md`
  for every dispatch, routes on worker return values, reports an inter-phase
  summary. **Does not write code, edit files, or run shell commands directly.**
- Phases run sequentially (A → B → C → D). Within a phase, may fan out
  to multiple parallel `Agent` calls for independent sub-tasks.

**Human pause checkpoints — §3.2 ONLY:**
These pauses apply in dispatch mode and do NOT apply to §3.1 autonomous runs.

- Before each phase transition: explicit go-ahead required from the user.
- If a worker hits the two-fix limit: stop and present OPEN QUESTIONS to
  the user before proceeding.
- Before any T1–T3 gate action (per §2).
- Before pushing to a remote branch (unless explicitly pre-authorized for
  THIS session for a NAMED branch).
- If a worker proposes editing `CLAUDE.md`, this file, or
  `mart_recovery_state.sql`.

**Inter-phase summary format (§3.2 sessions):**

```
PHASE <letter> — <name>
DONE: <one sentence>
CHANGED FILES: <list, or "none">
TESTS: <pass>/<total>
IDEMPOTENCY CHECK: <Phase B only: fresh rows / reload rows added — expect reload = 0>
OPEN QUESTIONS: <bulleted, or "none">
NEXT RECOMMENDATION: <next phase, or "pause for user">
```

#### Example dispatch: categories loader (BACKLOG Feature 1)

The full dispatch script for implementing the HK categories loader follows.
Use this as the paste-to-session prompt when running in §3.2 mode for
that specific feature.

---

**Scope: what "ship" means**

`ingest/loaders/categories.py:13` is a `NotImplementedError` stub. Six HK
category types — `SleepAnalysis`, `MindfulSession`, `AudioExposureEvent`,
`HighHeartRateEvent`, `LowHeartRateEvent`, `AppleStandHour` — are exported
by Health Auto Export but skipped at ingest. The deliverable is a working
loader that lands rows in `raw.categories` with the two-level idempotency
contract (SHA file ledger + ON CONFLICT row dedup, single transaction),
is dispatched by `ingest/loaders/batch.py`, and is observable in the
warehouse after a real export.

**This is loader-only.** No `stg_categories.sql`, no marts, no Streamlit.
Staging and downstream consumers are explicitly out of scope.

**Artifacts to ship:**
- `scripts/init_raw_schema.sql` — append `raw.categories` DDL after the workouts block
- `ingest/loaders/categories.py` — implement `parse_categories_csv` and `load_categories_csv`
- `ingest/loaders/batch.py` — import + register the new loader
- `tests/test_categories_loader.py` — new file, parser-only unit tests

---

**Phase A — Build & unit-test the loader**

**Worker:** `loader-engineer`

**Files in scope:**
- `scripts/init_raw_schema.sql` (append after workouts block at line 77)
- `ingest/loaders/categories.py` (replace the stub)
- `ingest/loaders/batch.py` (extend dispatch table + add import)
- `tests/test_categories_loader.py` (new file)

**Files OUT of scope:** All `transform/models/**`, all `app/**`,
`ingest/loaders/quantities.py`, `ingest/loaders/workouts.py`,
`transform/models/sources.yml` (already declares `categories` at line 10).

**DDL to append to `scripts/init_raw_schema.sql`:**

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

**Loader structure** (parallel to `ingest/loaders/quantities.py`):

- `_HK_TO_SNAKE` maps: `type → category_type`, `value → category_value`,
  `sourceName → source_name`, `sourceVersion → source_version`,
  `productType → product_type`, `device`, `startDate → start_ts`,
  `endDate → end_ts`, `HKTimeZone → hk_time_zone`,
  `HKHeartRateEventThreshold → hk_heart_rate_threshold`.
- Required columns (post-rename): the common six. The two optional metadata
  columns are added as NaN if missing (mirroring `workouts.py:119-121`).
- `parse_categories_csv(path)` strips the optional `sep=,` Excel hint,
  renames per the map, parses `start_ts` / `end_ts` as UTC-aware pandas
  timestamps, raises `ValueError` on missing required columns.
- `load_categories_csv(path, engine=None) -> LoadResult` — fast-path SHA
  check outside the transaction; inside `engine.begin()` records the file
  ledger then upserts. ON CONFLICT `index_elements=["category_type",
  "source_name", "start_ts"]`.
- Module-local helpers (copies from quantities.py): `_already_loaded`,
  `_record_file`, `_upsert_rows`, `_records_with_none_for_nan`.

**Batch registration:**
- `ingest/loaders/batch.py:24` — add `from ingest.loaders.categories import load_categories_csv`.
- `ingest/loaders/batch.py:80` — extend the `loaders` dict with `"categories"` using the injectable-parameter pattern.

**Parser tests** (no DB — mirrors `tests/test_quantities_loader.py`):

1. Sleep stage row → `category_type="SleepAnalysis"`, `category_value="asleepCore"`, `end_ts > start_ts`.
2. Mindful session row → `value="notApplicable"`, has duration.
3. `HighHeartRateEvent` row → `hk_heart_rate_threshold` literal preserved (e.g. `"120 count/min"`).
4. `AppleStandHour` row → `category_value="stood"`, point-in-time.
5. Missing optional columns → values land as `None`, parse succeeds.
6. Missing required column → raises `ValueError`.
7. `sep=,` Excel hint stripped.
8. Empty file (header only) → empty DataFrame, no exception.

**Success criteria (Phase A):**
- `uv run ruff check ingest/loaders/categories.py ingest/loaders/batch.py tests/test_categories_loader.py` exits 0
- `uv run pytest tests/test_categories_loader.py` green
- `uv run pytest tests/test_batch_loader.py` still green
- `mart_recovery_state.sql` byte-identical to pre-phase state

---

**Phase B — Real-export verification**

**Worker:** `loader-engineer` (second dispatch — fresh context)

No file edits. Execution + observation only.

```bash
docker exec -i health_postgres psql -U health -d health \
  < scripts/init_raw_schema.sql
uv run python -m ingest.flows.weekly_load
docker exec health_postgres psql -U health -d health -c \
  "SELECT category_type, COUNT(*) FROM raw.categories GROUP BY 1 ORDER BY 1;"
uv run python -m ingest.flows.weekly_load   # second run — idempotency check
docker exec health_postgres psql -U health -d health -c \
  "SELECT COUNT(*) FROM raw.categories;"
```

**Success criteria (Phase B):**
- Non-zero rows for populated types: `SleepAnalysis` (~832), `MindfulSession` (~7),
  `HighHeartRateEvent` (~3), `AppleStandHour` (~706). Zero rows for
  `AudioExposureEvent` and `LowHeartRateEvent` is acceptable (header-only CSVs).
- `raw.file_inventory` gains one row per category CSV.
- Second run reports `LoadResult(skipped=True)` for each category file, and
  row count after run 2 equals row count after run 1. **Hard gate (§2).**

---

**Phase C — Full project gate (regression check)**

**Worker:** `verifier` (read-only)

```bash
uv run ruff check .
uv run pytest
uv run dbt parse --project-dir transform --profiles-dir transform
uv run dbt build  --project-dir transform --profiles-dir transform
```

All four must exit 0. On failure: dispatch `loader-engineer` with a targeted
fix brief, then re-dispatch `verifier`. Two-fix limit (§2) — pause for user
on the third attempt.

---

**Phase D — Commit and PR**

**Worker:** `loader-engineer`

1. Confirm current branch is `feat/categories-loader`. If on `main`, pause for user.
2. Stage named files only (NEVER `git add -A`):
   ```
   git add ingest/loaders/categories.py ingest/loaders/batch.py \
           scripts/init_raw_schema.sql tests/test_categories_loader.py \
           .claude/orchestrator-prompt.md
   ```
3. Commit with HEREDOC title `feat: implement HK categories loader (BACKLOG Feature 1)`.
4. `git push -u origin feat/categories-loader` — **pre-authorized for THIS session ONLY for this named branch.** Force-push, merge to main, and direct push to main remain forbidden.
5. Open a PR via `gh pr create`.

**End state:** Phase D completes when the PR is open and its URL has been reported.

---

## §4 Precedence

1. **§1 Invariants always win**, in every mode.
2. **§2 Gates always win**, in every mode.
3. **§3.2's mandatory human pauses apply ONLY in §3.2.** An autonomous
   (§3.1) session MUST NOT deadlock on dispatch-mode pause checkpoints. It
   should self-check the corresponding §2 gate and proceed if the gate
   passes — or stop-and-surface if the gate would be violated.
4. When a session prompt says "drive the orchestrator pipeline" or
   "use the orchestrator" without specifying a mode: **default to §3.1
   (autonomous).** Invoke §3.2 only when the prompt explicitly requests
   human checkpoints at each phase boundary.
5. A session cannot unilaterally promote itself from §3.1 to §3.2 to gain
   pause checkpoints it couldn't otherwise justify. Gates and invariants are
   the right tool for that — not mode-switching.
