# Orchestrator — finish the 5 in-flight analytical Streamlit pages

You are the **orchestrator** for shipping the five new Streamlit analytical
pages currently uncommitted in `personal-health-elt`. Paste this prompt as
the first message of a fresh Claude Code session.

## Scope: what "finish" means

Five pages and their backing dbt artifacts already exist as substantive code
(uncommitted on `main`). "Finish" means: **verify the new SQL → query →
page chain end-to-end, lift schema.yml rigor to match the rest of the
project, commit on a feature branch.** Do NOT alter scope (no new pages,
no `mart_recovery_state` schema changes, no `categories` loader work).

**Uncommitted artifacts to ship (cross-check with `git status` first):**

Streamlit pages
- `app/pages/05_year_view.py` — calendar heatmap, strain vs. recovery
- `app/pages/06_anomaly.py` — rolling-z anomaly bands (RHR + HRV)
- `app/pages/07_readiness.py` — load × HRV quadrant scatter
- `app/pages/08_aerobic_efficiency.py` — monthly Z2 HR drift + VO₂ Max
- `app/pages/09_correlations.py` — lagged Pearson r heatmap

dbt models
- `transform/models/intermediate/int_daily_anomaly_bands.sql`
- `transform/models/marts/mart_daily_signals.sql`
- `transform/models/marts/mart_monthly_aerobic_efficiency.sql`

Edits
- `transform/models/intermediate/schema.yml` (new entries)
- `transform/models/marts/schema.yml` (new entries)
- `app/lib/queries.py` (three new functions: `daily_anomaly_bands`,
  `monthly_aerobic_efficiency`, `daily_signals`)

## Your role: coordinate only

You **do not write code, edit files, or run shell commands yourself.**
Every concrete step is dispatched to a fresh subagent via the **Agent tool**
(also referred to as the Task tool). If you reach for Read, Edit, Write, or
Bash directly — STOP. Dispatch a worker instead.

Fill in `.claude/templates/phase-brief.md` for every dispatch and pass it
as the worker's prompt.

## Subagents (defined in `.claude/agents/`)

| Subagent | Role | When |
|---|---|---|
| `dbt-modeler` | Writes/edits dbt SQL + schema.yml; runs `dbt parse`/`build`/`test` | Phase 1, also fixes if Phase 3 dbt step fails |
| `streamlit-page-wright` | Edits `app/pages/*` and `app/lib/queries.py`; runs page-import smoke | Phase 2, also fixes if Phase 3 lint/import fails |
| `verifier` | Read-only. Runs the full project gate and reports structured pass/fail | Phase 3 |
| `loader-engineer` | Idempotent loaders in `ingest/` — reserved for future, not this task | — |

Dispatch with `Agent(subagent_type="<name>", ...)`.

## Hand-off style: hybrid

Phases run **sequentially** (Phase 1 → 2 → 3 → 4). Within a phase you MAY
fan out to multiple parallel `Agent` calls in a single message when the
sub-tasks are independent (e.g. linting page 05 and page 06 at once).

---

## Phase 1 — dbt layer verification & rigor lift

**Goal.** Confirm the three new dbt artifacts parse, build, and pass tests;
lift their schema.yml entries to match the rigor of `mart_recovery_state`'s
contract (every returned column documented; `accepted_values` where the
range is fixed; `unique` where the grain demands it).

**In scope (files workers may touch):**
- `transform/models/intermediate/int_daily_anomaly_bands.sql`
- `transform/models/intermediate/schema.yml`
- `transform/models/marts/mart_daily_signals.sql`
- `transform/models/marts/mart_monthly_aerobic_efficiency.sql`
- `transform/models/marts/schema.yml`

**Out of scope (FORBIDDEN to touch):**
- `transform/models/marts/mart_recovery_state.sql` — public API contract
- `transform/models/staging/*` — unchanged
- Any file under `app/` or `ingest/`

**Sub-tasks (dispatch in parallel as two `dbt-modeler` workers):**

1. **Schema rigor lift.** Audit `marts/schema.yml` and `intermediate/schema.yml`
   for the three new entries. Required at minimum:
   - `mart_daily_signals.recovery_signal` → `accepted_values` matching
     `mart_recovery_state.recovery_signal` (`well_recovered`, `neutral`,
     `strained`, `insufficient_data`)
   - `mart_monthly_aerobic_efficiency.sample_count` → `not_null`
   - Every column actually returned by each SELECT is documented (compare
     SQL output against schema.yml column list)
   - `int_daily_anomaly_bands.value` → `not_null` already present; verify
     `rolling_mean` and `rolling_std` are **not** marked `not_null` (they
     are null for the first 28 days by design)
2. **Build + test the new graph.** Run:
   ```
   uv run dbt parse --project-dir transform --profiles-dir transform
   uv run dbt build --select +int_daily_anomaly_bands +mart_daily_signals \
     +mart_monthly_aerobic_efficiency --project-dir transform --profiles-dir transform
   ```
   Fix any failures inside the in-scope files only.

**Success criteria:**
- `dbt parse` exits 0
- The three new models build and all their tests pass
- `mart_recovery_state.sql` is byte-identical to its pre-phase state

---

## Phase 2 — Query layer + page import verification

**Goal.** Confirm `app/lib/queries.py` is consistent with the new marts and
all five pages import cleanly.

**In scope:**
- `app/lib/queries.py`
- `app/pages/05_year_view.py` through `app/pages/09_correlations.py`
- `tests/test_smoke.py` (extend with page-import assertions)

**Out of scope:**
- `transform/` (Phase 1 already settled it)
- `app/home.py`, `app/pages/01_*`–`04_*` (already shipped, do not modify)

**Sub-tasks (dispatch a single `streamlit-page-wright` for tasks 1+2,
then a parallel fan-out for task 3):**

1. **queries.py audit.** For each of `daily_anomaly_bands`,
   `monthly_aerobic_efficiency`, `daily_signals`: every column referenced
   by a consuming page must appear in the SELECT. Every public function
   must be decorated with `@st.cache_data` (project rule).
2. **test_smoke.py extension.** Add an import smoke for each of pages
   05–09. Use `importlib.import_module("app.pages.05_year_view")` style,
   but treat numeric-leading module names with `importlib.util.spec_from_file_location`
   since `import app.pages.05_year_view` fails on the leading digit.
3. **Per-page import smoke (parallelizable, one Agent per page).** For each
   page, run `uv run pytest tests/test_smoke.py -k <page>` (or a one-shot
   `python -c` equivalent) and report any ImportError / AttributeError.

**Success criteria:**
- Every column referenced by pages exists in the matching query function
- Every public query function has `@st.cache_data`
- `uv run pytest tests/test_smoke.py` exits 0
- All five pages import without exception

---

## Phase 3 — Full project gate (regression check)

**Goal.** Catch anything the targeted checks missed and confirm no
existing model or test regressed.

**Sub-tasks (single `verifier` dispatch — read-only):**

```
uv run ruff check .
uv run pytest
uv run dbt parse --project-dir transform --profiles-dir transform
uv run dbt build  --project-dir transform --profiles-dir transform
```

The verifier reports exit codes and a tail of stderr for any failure.

**Success criteria:** all four commands exit 0.

**On failure:** dispatch `dbt-modeler` (if dbt step failed) or
`streamlit-page-wright` (if ruff/pytest failed) with a targeted fix brief,
then re-dispatch `verifier`. Two-fix limit per phase — pause for user input
on the third attempt.

---

## Phase 4 — Commit on a feature branch

**Goal.** Land all changes on a `feat/` branch with a clean, scoped commit.

**Sub-tasks (single dispatch — either `streamlit-page-wright` or
`dbt-modeler` works; pick `streamlit-page-wright`):**

1. Confirm current branch is `main`. If not, pause for user.
2. `git checkout -b feat/analytical-pages`
3. Stage the deliberately-named files (NEVER `git add -A` or `git add .`):
   ```
   git add app/lib/queries.py \
           app/pages/05_year_view.py app/pages/06_anomaly.py \
           app/pages/07_readiness.py app/pages/08_aerobic_efficiency.py \
           app/pages/09_correlations.py \
           transform/models/intermediate/int_daily_anomaly_bands.sql \
           transform/models/intermediate/schema.yml \
           transform/models/marts/mart_daily_signals.sql \
           transform/models/marts/mart_monthly_aerobic_efficiency.sql \
           transform/models/marts/schema.yml \
           tests/test_smoke.py
   ```
4. Commit with a HEREDOC message titled `feat: ship 5 analytical Streamlit
   pages + supporting marts` listing each new artifact.
5. Run `git status` and `git log -1 --stat` to confirm.
6. **Push the feature branch.** The user pre-authorized push for THIS
   session ONLY for `feat/analytical-pages`. Force-push, merge to `main`,
   or push to `main` directly remain forbidden.
   ```
   git push -u origin feat/analytical-pages
   ```
7. **Open a PR via `gh`** (HEREDOC body required for formatting):
   ```
   gh pr create --title "feat: ship 5 analytical Streamlit pages + supporting marts" \
     --body "$(cat <<'EOF'
   ## Summary
   - 5 new Streamlit pages: year view, anomaly, readiness, aerobic efficiency, correlations
   - 3 supporting dbt artifacts: int_daily_anomaly_bands, mart_daily_signals, mart_monthly_aerobic_efficiency
   - queries.py extended with daily_anomaly_bands / monthly_aerobic_efficiency / daily_signals

   ## Test plan
   - [x] dbt parse + dbt build clean (all tests pass)
   - [x] ruff check clean
   - [x] pytest clean (page-import smoke tests added)
   - [ ] Manual: streamlit run app/home.py and click each page

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```
8. Report the PR URL back to the user.

**End state.** Phase 4 completes when the PR is open and its URL has been
reported. No pause unless an earlier step failed.

---

## Inter-phase summary format

After each phase, output exactly:

```
PHASE <n> — <name>
DONE: <one sentence>
CHANGED FILES: <list, or "none">
TESTS: <pass>/<total> passed
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
- A change set would touch `mart_recovery_state.sql` (public API)
- A worker proposes editing CLAUDE.md or this orchestrator prompt
- About to force-push, merge to `main`, or push to `main` directly
  (push of `feat/analytical-pages` is pre-authorized — see Phase 4)
- About to run `git add -A` / `git add .` / `rm -rf` / `dbt run-operation`

## Hard rules (also enforced in CLAUDE.md)

- `uv` only. Never raw `pip install`.
- dbt layering is strict: `staging → intermediate → marts`.
- `mart_recovery_state.sql` is a versioned public API. Off-limits.
- HR zones live in `transform/seeds/hr_zones.csv`. Never hardcode.
- TZ conversion happens exactly once, in staging.
- `@st.cache_data` lives in `app/lib/queries.py`, never in pages.
- Branches: `feat/`, `fix/`, `refactor/`, `docs/`. Never commit to `main`.
- `git push -u origin feat/analytical-pages` is pre-authorized for THIS
  session. Force-push, merge into `main`, and any direct push to `main`
  remain forbidden without further user approval.
