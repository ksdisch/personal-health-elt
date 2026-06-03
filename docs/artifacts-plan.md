# Canonical Engineering Artifacts — Audit & Generation Plan

## Changelog
- 2026-06-03: Generated ROADMAP.md at `ROADMAP.md` (now/next/later forward narrative restructured from BACKLOG.md; BACKLOG kept as the detailed live backlog and cross-linked per item). Status: 🟢 → ✅.
- 2026-06-03: Generated postmortem template at `docs/postmortems/TEMPLATE.md` (adapted to a single-user data-pipeline severity scale S1–S3 + a pipeline-specific "Data-integrity verification" section). Status: 🟢 → ✅.
- 2026-06-03: Generated flow-failure runbook at `docs/runbooks/weekly-load-failure.md` (key message: re-running `weekly_load` is safe — idempotent loaders; also documents the real detection signals and the no-alert-on-flow-failure gap). Status: 🟢 → ✅. **This completes Tier-2.**
- 2026-06-03: Generated dbt lineage diagram at `docs/diagrams/dbt-lineage.mmd` (full DAG, layer-grouped) and `weekly_load` sequence diagram at `docs/diagrams/weekly-load-sequence.mmd`; both live-rendered via mermaid-cli. Status: 🟢 → ✅. (`dbt docs generate` in CI remains open — it's a `.github/` code change, out of artifacts-generate scope.)
- 2026-06-01: Generated CHANGELOG.md at `CHANGELOG.md` (Keep a Changelog + SemVer, backfilled v0.1.0–v0.3.0 from PRs #1–#33) + git tags v0.1.0/v0.2.0/v0.3.0. Status: 🟢 → ✅.
- 2026-06-01: Generated ADRs 0001–0007 at `docs/adr/000N-*.md` (+ index `docs/adr/README.md`), all Accepted. Status: 🟢 → ✅.
- 2026-05-31: Generated Tier-1 artifacts — README refresh, `docs/reference/data-dictionary.md`, `docs/diagrams/system-context.mmd`, `docs/diagrams/raw-erd.dbml` (merged via PR #33).

> **Status:** Plan only. This document is the source of truth for a follow-up
> generation session. It does **not** create the artifacts it recommends, and
> no source code was modified to produce it.
>
> **Generated:** 2026-05-31 · **Repo:** `personal-health-elt` ·
> **Branch audited:** `claude/focused-gates-hYTSR` (1 commit ahead of `main`)
>
> **Method:** Phase-1 discovery was run as a 6-agent parallel read-only sweep
> (tree inventory, manifests/entry points, source architecture, existing docs,
> git history, data-model/contract surface). 132 tracked files, 50 commits,
> 30 merged PRs surveyed.

---

## Confirmed decisions (drive the recommendations below)

These three were confirmed with the maintainer before the audit was written:

1. **Audience weighting → Portfolio-first.** Reviewer-credibility signal is
   weighted highest (accurate README, ADRs, architecture diagram, CHANGELOG).
   Operational docs are still recommended but sit a tier lower.
2. **`mart_recovery_state` contract doc → in this repo, full.** A `docs/`
   data dictionary will document both the mart columns/enum **and** the
   Firestore document shape (`users/{uid}/recovery_state/{latest,history}`).
   This repo becomes the source of truth for all three consumers.
3. **Diagrams → DBML + Mermaid split.** DBML for the **raw relational ERD**
   (real PK/FK, generatable from `scripts/init_raw_schema.sql`); Mermaid for
   the **dbt DAG** (SELECT-lineage, not keys) and the **system/C4 context**
   diagram.

---

## Phase 2 — Project profile (recap)

| Field | Finding |
|---|---|
| **Shape** | **Data pipeline (ELT)**, hybrid — Postgres-backed Apple Health ELT + 13-page Streamlit analytics app + a versioned "public-API" mart feeding 3 consumers. Not a library/service. |
| **Primary languages** | Python 3.12 (57 files), SQL (33 — 25 dbt models, 5 dbt tests, 2 macros, 1 init schema), YAML (10), Markdown (11). |
| **Stack** | `uv` · pandas 2.2 · psycopg3 · SQLAlchemy 2.0 · **Prefect 3.x** · **dbt-core 1.8+ / dbt-postgres** · **Streamlit 1.38+** · `anthropic` SDK · `firebase-admin` · Ruff + pytest + mypy · GitHub Actions. |
| **Datastores** | **Postgres 16** (Docker): `raw.*` → `analytics_staging/intermediate/marts.*`. **Firestore** (one-way feed to Tempo PWA). pgAdmin for admin. 7 raw tables, hub-and-spoke FK to `raw.file_inventory`. |
| **Deployment / orchestration** | Self-hosted **Prefect** (`flow.serve`, cron `0 6 * * 0` Sun 06:00 CT) via macOS **launchd** templates in `deploy/`. `docs/DEPLOYMENT.md` targets Streamlit Cloud + managed Postgres. No app Dockerfile (compose = Postgres + pgAdmin only). |
| **Audience** | **Portfolio** (Analytics/Data Engineer roles) **+ personal single-user tool**. MIT-licensed, effectively private. |
| **Maturity** | **Active dev → light production.** Real scheduled runs, 3 live mart consumers, hardened CI. But ~5 weeks old, no tags, stale README. |
| **Team size** | **Solo** — 1 human (`ksdisch`, two git identities), AI-assisted (5 `Claude` co-author commits). 30 numbered PRs, conventional commits. |
| **Active areas** | `transform/models` (most-touched — forecasting/sleep/HRR marts) · `app/pages` (Ask, forecast) · `ingest/loaders` (calendar/weather, idempotency) · `ingest/flows` (Prefect deploy) · `scripts/` (Firestore push). |
| **Existing docs/diagrams** | README (380 ln, polished but stale) · CLAUDE.md (current) · BACKLOG.md (current) · docs/automation.md (runbook) · docs/DEPLOYMENT.md · LICENSE (MIT) · 3 screenshots · CI workflow · `.claude/` orchestrator artifacts. |
| **Notable gaps** | README under-describes reality (4 pages/~7 marts vs **12 pages / 17 marts**; omits Firestore + daily-coach consumers); no data dictionary for the public-API mart; no ADRs; no committed architecture/lineage diagram (only stale README ASCII). |

---

## Phase 3 — Audit

Legend: ✅ present & healthy · ⚠️ stale/thin · 🟢 recommended (missing, high value) ·
🟡 optional · ⛔ not applicable.

### Repo hygiene

| Artifact | Status | Evidence-anchored justification |
|---|---|---|
| `README.md` | ⚠️ STALE | Polished (380 ln, badges, ASCII diagram), but **materially wrong**: claims "4 pages" (actual `app/pages/` = **12**), shows ~7 marts (actual `transform/models/marts/` = **17**), describes **1** `mart_recovery_state` consumer (actual **3**: weekly-review skill, Tempo Firestore feed `push_recovery_state.py`, daily-coach), CI claim omits the `mypy` step that ci.yml actually runs, "Live app" URL still a TODO. |
| `LICENSE` | ✅ PRESENT | MIT, "Copyright (c) 2026 Kyle Disch" — matches the README MIT badge. |
| `.env.example` | ✅ PRESENT | Tracked; documents all Postgres + optional vars (OpenWeather, Calendar, Pushover, Anthropic, Tempo Firebase). **Open question:** a `.env` also exists at repo root — confirm it is gitignored and uncommitted (not part of this audit's scope to change). |
| `CHANGELOG.md` | ✅ PRESENT | Generated `CHANGELOG.md` (Keep a Changelog + SemVer), backfilled `v0.1.0`/`v0.2.0`/`v0.3.0` from PR history #1–#33. 30 merged PRs (#1–#30), **zero git tags**, no release history. Portfolio reviewers read a changelog as a velocity signal; the existing conventional-commit style (`feat/fix/refactor/test/docs/chore/ci`) makes it semi-automatable. |
| PR template | 🟢 RECOMMENDED | Clear PR-numbered workflow exists (#1–#30) but `.github/` holds **only** `ci.yml` — a `PULL_REQUEST_TEMPLATE.md` standardizes the description shape for the portfolio audience. |
| `justfile` | 🟢 RECOMMENDED (light) | Run commands are long (`uv run dbt build --project-dir transform --profiles-dir transform`) and live only in CLAUDE.md prose; a `justfile` wrapping them reads well to reviewers and removes copy-paste friction. |
| `CONTRIBUTING.md` | 🟡 OPTIONAL | Solo repo, but the cheapest portfolio credibility add — a 1-screen "dev loop / how to run tests" liftable from README's command section. |
| Issue templates | 🟡 OPTIONAL | Low value for a solo repo with no external issue flow. |
| `CODE_OF_CONDUCT.md` | 🟡 OPTIONAL | Only relevant if opening to outside contributors; no signal of that today. |
| `SECURITY.md` | 🟡 OPTIONAL | Handles personal health data routed through iCloud (per automation.md); a short data-handling/trust-boundary note has mild portfolio value but low urgency for a single user. |

### Decision & design

| Artifact | Status | Justification |
|---|---|---|
| ADRs | ✅ PRESENT | Generated `docs/adr/0001`–`0007` (+ index `docs/adr/README.md`), all Accepted. Several **hard-to-reverse** decisions live only as CLAUDE.md prose and deserve numbered, append-only records — strong Data-Eng portfolio signal: (1) **UTC→America/Chicago at staging only**; (2) **multi-source dedup priority** Apple Watch > iPhone > 3rd-party via `row_number()`; (3) **two-level idempotency** (SHA file ledger + row-level `ON CONFLICT`, single transaction); (4) **self-hosted Prefect over GHA/launchd** (data locality — see automation.md rationale); (5) **`mart_recovery_state` as a versioned public API** with lockstep consumers; (6) **pure-SQL Holt's-method forecasting** (#28) instead of a Python ML dep; (7) **dbt-1.8 nested `accepted_values`** contract form. |
| Design Doc / RFC / Tech Spec | 🟡 OPTIONAL | Most features already shipped, so retroactive specs are lower-leverage than ADRs. The one genuine candidate: a short design doc for the **Holt's-method forecasting marts** (`mart_forecast_bands`/`mart_forecast_backtest` + `holt_forecast` macro), since the math/backtest design isn't obvious from SQL. |
| PRD | ⛔ NOT APPLICABLE | Single-user personal tool; the "product" is the maintainer. README's "What this demonstrates" already covers the why. |
| Postmortem / RCA (instances) | ⛔ N/A (yet) | No incidents recorded. The **template** is recommended (see Ops). |

### Planning

| Artifact | Status | Justification |
|---|---|---|
| `BACKLOG.md` | ✅ PRESENT | 291 ln, current to 2026-05-12, typed items (Feature/Improvement/Refactor/Exploration/Bug) with Why/Acceptance/Size/Added. Functions as the live backlog. |
| Roadmap (now/next/later) | ✅ PRESENT (`ROADMAP.md`) | No now/next/later framing exists. README's roadmap is **week-by-week and stale** (stops at "Week 4"; reality shipped through #30). A `ROADMAP.md` (or a now/next/later header section in BACKLOG) gives reviewers a forward narrative. |
| User stories | ⛔ N/A | Solo personal tool. |
| Sprint plan / WBS / RACI / OKRs / Gantt / Kanban | ⛔ N/A | Solo portfolio repo — these are team-coordination artifacts with no audience here. |

### Diagrams

| Artifact | Status | Justification |
|---|---|---|
| **ERD (raw layer)** | 🟢 RECOMMENDED · **DBML** | `scripts/init_raw_schema.sql` gives explicit PKs, FKs (all loader tables → `raw.file_inventory.sha256`), indexes, and `COMMENT ON` — an ERD generates almost mechanically. The `file_inventory` hub-and-spoke is the centerpiece of the idempotency story. DBML round-trips from Postgres DDL and models FK/composite PKs faithfully. |
| **dbt DAG / data lineage** | ✅ PRESENT · **Mermaid** | Generated `docs/diagrams/dbt-lineage.mmd` (full DAG, layer-grouped; live-rendered). 25 models across strict staging(5)→intermediate(3)→marts(17). These are SELECT-lineage edges, **not** key relationships — Mermaid `flowchart` (not an ERD) is the correct notation. Centerpiece: `mart_recovery_state` as the hub feeding 3 consumers. |
| **C4 Context / Container** | 🟢 RECOMMENDED · **Mermaid** | Replaces the **stale** README ASCII diagram. Shows CSV drop → loaders → Postgres → dbt → {Streamlit app, weekly-review skill, Tempo PWA Firestore, daily-coach}. Highest single portfolio-signal diagram; can be embedded in the refreshed README. |
| Sequence diagram | ✅ PRESENT · **Mermaid** | Generated `docs/diagrams/weekly-load-sequence.mmd` (live-rendered). The `weekly_load` flow is a clean sequence: hash CSV → load (quantities/categories/workouts) → optional weather/calendar → `dbt build` (skipped if 0 new rows) → notifications → Firestore push, with retries. Makes the orchestration legible. |
| C4 Component | 🟡 OPTIONAL | Per-container component breakdown; lower leverage than context+container. |
| State diagram | 🟡 OPTIONAL | `recovery_signal` is a bucketing (`well_recovered/neutral/strained/insufficient_data`), not a true state machine; a small classification diagram could live inside the data dictionary instead. |
| Deployment / topology / cloud arch | 🟡 OPTIONAL | The laptop + launchd + Prefect + Postgres + Streamlit Cloud + Firestore topology is non-trivial but adequately covered by the C4 Container diagram + automation.md. |
| DFD / swimlane / activity / UML class | 🟡 OPTIONAL | Overlap with C4 context + sequence; class diagram has little to model (not OO-heavy). |
| Dimensional model (star/snowflake) | ⛔ NOT APPLICABLE | The marts are **denormalized daily-grain snapshots**, not a fact/conformed-dimension star schema. Dimensional notation would misrepresent the model. |
| Wireframes / mockups | ⛔ NOT APPLICABLE | Streamlit auto-generates UI; the 3 `docs/screenshots/` PNGs already serve as the visual record. |

### Ops & reliability

| Artifact | Status | Justification |
|---|---|---|
| Runbook (scheduled refresh) | ✅ PRESENT | `docs/automation.md` (237 ln) — rationale, `flow.serve()` mechanism, schedule, iCloud export path, launchd setup, manual run, sleep/pmset caveat. Solid. |
| Runbook (cold-start / cloud deploy) | ✅ PRESENT | `docs/DEPLOYMENT.md` (236 ln) — managed-Postgres provisioning, cold-start import, deploy targets, troubleshooting. |
| Runbook (flow-failure re-run) | ✅ PRESENT (`docs/runbooks/weekly-load-failure.md`) | The flow already emits structured ERROR alerts + Pushover (#8, #23) and is laptop-bound (known tradeoff). A short "weekly_load failed / laptop asleep → how to re-run safely" runbook closes the loop (loaders are idempotent, so safe to re-run). |
| Postmortem template | ✅ PRESENT (`docs/postmortems/TEMPLATE.md`) | Cheap, and there are real failure surfaces (scheduled flow on a sleeping laptop, notification pipeline, dbt build drift). Gives a home for the first incident write-up. |
| Playbook (per-scenario) | 🟡 OPTIONAL | E.g. "export didn't sync from iCloud", "dbt build failed mid-flow" — useful but lower priority under portfolio-first weighting. |
| SLI / SLO / SLA | 🟡 OPTIONAL | No external SLA (single user). But `dbt source freshness` is already configured (#5) — that's a ready-made **freshness SLI**; a light "data ≤7 days fresh" SLO note would formalize it. |
| On-call / escalation | ⛔ NOT APPLICABLE | Solo; "escalation" is a Pushover notification to the one user. |

### Knowledge

| Artifact | Status | Justification |
|---|---|---|
| **Data dictionary** | 🟢 RECOMMENDED (**top priority**) | Confirmed scope: document `mart_recovery_state` columns + the `recovery_signal` enum + the Firestore doc shape (`users/{uid}/recovery_state/{latest,history}`), plus a catalog of the 17 marts and 7 raw tables. Today the contract lives **only** in `schema.yml` dbt tests (`accepted_values` + `unique(day)`) — invisible to the 3 consumers as human-readable docs. |
| Glossary | 🟡 OPTIONAL | Heavy domain jargon (ACWR, TRIMP, Zone 2, HRV SDNN, HRR, hypnogram, `recovery_signal`). Best folded in as a section of the data dictionary rather than a standalone file. |
| Onboarding doc | 🟡 OPTIONAL | CLAUDE.md + README already serve the solo author + AI sessions; a separate onboarding doc would be redundant. |
| API docs (OpenAPI/Swagger) | ⛔ NOT APPLICABLE | No HTTP API. The de-facto API is the mart contract — covered by the data dictionary. |
| Wiki | ⛔ NOT APPLICABLE | In-repo `docs/` suffices for a solo repo. |

---

## Phase 4 — Generation & maintenance plan

### 1. Priority order (leverage-to-effort, portfolio-weighted)

**Tier 1 — this week** (front-door credibility + the confirmed contract doc)

| # | Artifact | Why first |
|---|---|---|
| 1 | **README refresh** | It's the front door and it's materially wrong (4→12 pages, 7→17 marts, 1→3 consumers, CI claim). Highest leverage of any single edit. |
| 2 | **Data dictionary** (`mart_recovery_state` + Firestore shape) | Confirmed top priority; the public-API contract with 3 consumers currently has no human-readable form. |
| 3 | **C4 Context/Container diagram** (Mermaid) | Replaces the stale ASCII art; embeds into the refreshed README — do alongside #1. |
| 4 | **Raw-layer ERD** (DBML) | Near-mechanical from `init_raw_schema.sql`; showcases the idempotency hub-and-spoke. High signal, low effort. |

**Tier 2 — this month** (decision record + lineage + history)

| # | Artifact |
|---|---|
| 5 | ✅ **ADRs 0001–0007** (the 7 decisions listed in the audit) — done |
| 6 | ✅ **dbt DAG lineage diagram** (Mermaid) — done. (`dbt docs generate` in CI still open — touches `.github/`, a code change.) |
| 7 | ✅ **CHANGELOG.md** + first **git tags** (backfill `v0.x` from PR history) — done |
| 8 | ✅ **`weekly_load` sequence diagram** (Mermaid) — done |
| 9 | ✅ **Postmortem template** (`docs/postmortems/TEMPLATE.md`) + **flow-failure runbook** (`docs/runbooks/weekly-load-failure.md`) — done |
| 10 | ✅ **ROADMAP.md** (`ROADMAP.md`, now/next/later, restructured from BACKLOG) — done |

**Tier 3 — nice-to-have**

| # | Artifact |
|---|---|
| 11 | `justfile` (wrap the documented `uv`/dbt commands) |
| 12 | PR template |
| 13 | Forecasting design doc (Holt's method + backtest) |
| 14 | CONTRIBUTING.md (1-screen dev loop) · Glossary (folded into data dictionary) |
| 15 | SLI/SLO freshness note · per-scenario playbook · SECURITY.md |

### 2. Per-artifact spec

| Artifact | Target path | Format | Effort | Dependencies |
|---|---|---|---|---|
| README refresh | `README.md` | Markdown | M | C4 diagram (#3) for the embedded architecture section |
| Data dictionary | `docs/reference/data-dictionary.md` (or `docs/data-dictionary.md`) | Markdown (+ tables) | M | Verify the `mart_recovery_state.sql` CTE typo flag first (see Open Questions); final mart schema |
| C4 Context/Container | `docs/diagrams/system-context.mmd` (embed in README) | Mermaid | S–M | none |
| Raw ERD | `docs/diagrams/raw-erd.dbml` | DBML | S–M | `scripts/init_raw_schema.sql` (stable, ready) |
| ADRs 0001–0007 | `docs/adr/000N-<slug>.md` | Markdown (MADR-lite) | M total (S each) | none — sourced from CLAUDE.md prose |
| dbt DAG lineage | `docs/diagrams/dbt-lineage.mmd` | Mermaid | M | optionally generated from `dbt docs` (see automation) |
| CHANGELOG + tags | `CHANGELOG.md` + `git tag` | Markdown / git | S–M | conventional-commit history (present) |
| weekly_load sequence | `docs/diagrams/weekly-load-sequence.mmd` | Mermaid | S | none — sourced from `ingest/flows/weekly_load.py` |
| Postmortem template | `docs/postmortems/TEMPLATE.md` | Markdown | S | none |
| Flow-failure runbook | `docs/runbooks/weekly-load-failure.md` | Markdown | S | none |
| ROADMAP | `ROADMAP.md` (root) | Markdown | S | BACKLOG.md |
| justfile | `justfile` (root) | just | S | none — wraps CLAUDE.md commands |
| PR template | `.github/PULL_REQUEST_TEMPLATE.md` | Markdown | S | none |
| Forecasting design doc | `docs/design/forecasting-marts.md` | Markdown | M | ADR for pure-SQL Holt's (#6 in ADR set) |
| CONTRIBUTING | `CONTRIBUTING.md` (root) | Markdown | S | README command section |

> **Note on `docs/` layout:** the existing convention is flat (`docs/automation.md`,
> `docs/DEPLOYMENT.md`). This plan introduces subdirectories (`adr/`, `design/`,
> `diagrams/`, `runbooks/`, `postmortems/`, `reference/`) for the *new* artifacts.
> Leave `automation.md`/`DEPLOYMENT.md` where they are (they're linked from
> README); optionally cross-link them from a future `docs/runbooks/` index.

### 3. Maintenance cadence

| Trigger | Refresh |
|---|---|
| **Per-PR** | README (when scope changes — pages/marts/consumers); inline architecture diagram when topology is touched; a CHANGELOG entry (or conventional-commit that auto-generates one). |
| **Per-release / tag** | Finalize CHANGELOG section; bump version; cut a `git tag`. |
| **Per-significant-decision** | New numbered, append-only ADR under `docs/adr/`. |
| **Per-incident** | New `docs/postmortems/YYYY-MM-DD-<incident>.md` from the template. |
| **Triggered — schema change** | Raw ERD (DBML) when `init_raw_schema.sql` changes; data dictionary when any `mart` schema or the Firestore doc shape changes — **in lockstep with all 3 `mart_recovery_state` consumers** per the CLAUDE.md contract rule. |
| **Triggered — topology change** | C4 context/container + `weekly_load` sequence diagram when the flow, datastores, or consumers change. |
| **Triggered — model change** | dbt DAG lineage diagram (or rely on CI `dbt docs generate`) when models are added/removed. |
| **Quarterly** | Roadmap re-prioritization; BACKLOG grooming; re-verify runbook steps (date-stamp the "last verified" line). |

### 4. Suggested automation (CI / dev-loop helpers)

| Automation | What it does | Notes |
|---|---|---|
| **`dbt docs generate` in CI** | Builds the lineage graph + catalog as a CI artifact (optionally publish manifest/catalog or a Pages site). | Slots into the existing `ci.yml` after the green `dbt build` step. Keeps the lineage diagram honest. |
| **Doc-freshness test** (repo-specific) | A pytest that counts `app/pages/*.py` and `transform/models/marts/*.sql` and greps README for the stated counts; fails if they drift. | Directly prevents the staleness this audit found ("4 pages / 7 marts"). High leverage, low effort. |
| **Markdown link-checker** | `lychee`/`markdown-link-check` workflow over `docs/` + README. | Catches the "Live app TODO" and dead links. |
| **Mermaid lint** | `mmdc`/`@mermaid-js/mermaid-cli` validates `docs/diagrams/*.mmd` in CI. | Prevents broken diagrams from merging. |
| **DBML validation** | `@dbml/cli` (`dbml2sql --postgres`) validates `docs/diagrams/*.dbml`; optionally diff against live `information_schema`. | Keeps the ERD in sync with `init_raw_schema.sql`. |
| **Conventional-commits → CHANGELOG** | `git-cliff` or `release-please` generates/maintains `CHANGELOG.md` from the existing conventional commits. | The repo already commits in conventional style — near-free. |
| **ADR-numbering pre-commit hook** | Small script asserting `docs/adr/` filenames are sequential, zero-padded, append-only. | Fits the existing `.pre-commit-config.yaml` (`language: system`). |

### 5. Naming conventions & structure

```
docs/
├── adr/
│   ├── 0001-timezone-normalization-at-staging.md
│   ├── 0002-multi-source-dedup-priority.md
│   ├── 0003-two-level-idempotency.md
│   ├── 0004-self-hosted-prefect-over-gha-launchd.md
│   ├── 0005-mart-recovery-state-public-api.md
│   ├── 0006-pure-sql-holt-forecasting.md
│   └── 0007-dbt18-nested-accepted-values.md
├── design/
│   └── forecasting-marts.md
├── runbooks/
│   ├── weekly-load-failure.md
│   └── (existing automation.md / DEPLOYMENT.md cross-linked)
├── postmortems/
│   ├── TEMPLATE.md
│   └── YYYY-MM-DD-<incident>.md
├── diagrams/
│   ├── system-context.mmd        # Mermaid C4 context/container
│   ├── dbt-lineage.mmd           # Mermaid flowchart of the 25-model DAG
│   ├── weekly-load-sequence.mmd  # Mermaid sequence
│   └── raw-erd.dbml              # DBML ERD of the raw schema
├── reference/
│   └── data-dictionary.md        # marts + Firestore contract + glossary
├── automation.md                 # (existing)
└── DEPLOYMENT.md                 # (existing)

# Root-level:
CHANGELOG.md · ROADMAP.md · justfile · CONTRIBUTING.md
.github/PULL_REQUEST_TEMPLATE.md
```

- **ADRs:** `docs/adr/NNNN-kebab-title.md`, zero-padded, sequential, append-only;
  status field (`Proposed/Accepted/Superseded`).
- **Diagrams:** `.mmd` for Mermaid, `.dbml` for DBML; the system-context diagram
  is *also* embedded inline in README's Architecture section.
- **Postmortems:** `docs/postmortems/YYYY-MM-DD-<incident>.md` from `TEMPLATE.md`.

---

## Open questions to resolve before generation

1. **`mart_recovery_state.sql` CTE flag.** A discovery agent flagged a possible
   missing leading comma on the `with_hrv_trend as (` CTE. CI runs `dbt build`,
   so it most likely compiles fine (false positive), but **verify before the
   data dictionary documents compiled lineage**. *(Not touched in this session —
   the file is contract-protected per CLAUDE.md.)*
2. **Root `.env` hygiene.** Discovery noted a `.env` at repo root alongside
   `.env.example`. Confirm it is gitignored and was never committed (history
   check) — relevant to a future SECURITY.md and to portfolio cleanliness.
3. **Firestore contract ownership.** The data dictionary will document the
   `users/{uid}/recovery_state` shape here (confirmed). Decide whether the
   **Tempo PWA repo** should link back to this doc as the canonical source, or
   keep its own copy — affects the lockstep-update rule.
4. **Tagging scheme.** No tags exist. Decide whether to backfill semantic tags
   from PR history (`v0.1.0`…) or start tagging from the next release only —
   determines how much CHANGELOG backfill is worthwhile.
5. **`docs/` subdir migration.** Confirm whether to keep `automation.md` /
   `DEPLOYMENT.md` flat (current links intact) or move them under
   `docs/runbooks/` (cleaner tree, but updates README links).

---

## Appendix — discovery evidence index

- **Tree:** 132 tracked files; Python 57 / SQL 33 / YAML 10 / MD 11. Top dirs:
  `ingest/` (loaders + flows + notifications), `transform/` (dbt: 5 staging /
  3 intermediate / 17 marts + 2 seeds + 2 macros + 5 singular tests), `app/`
  (home + 12 pages + `lib/queries.py`), `tests/` (21 modules), `scripts/`,
  `deploy/launchd/`, `docs/`.
- **dbt DAG hub:** `mart_recovery_state` ← `mart_daily_rhr` + `mart_daily_hrv` +
  `mart_training_load`; consumed by `weekly_health_review.py`,
  `push_recovery_state.py` (Firestore), `daily_workout_coach.py` (+ dbt exposures).
- **Contract surface:** `transform/models/marts/schema.yml` —
  `accepted_values(recovery_signal ∈ {well_recovered, neutral, strained,
  insufficient_data})` + `unique(day)` + `not_null`.
- **Raw ERD source:** `scripts/init_raw_schema.sql` — 7 tables, explicit PK/FK to
  `raw.file_inventory.sha256`, indexes, `COMMENT ON`.
- **Git:** 50 commits over ~5 weeks, 30 numbered PRs, 0 tags, conventional commits,
  solo (AI-assisted).
- **CI (`.github/workflows/ci.yml`):** ruff → mypy(ingest) → pytest+cov →
  init raw schema → dbt parse → dbt build (against empty Postgres).
