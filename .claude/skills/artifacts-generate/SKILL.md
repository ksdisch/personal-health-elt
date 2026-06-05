---
name: artifacts-generate
description: Generate engineering artifacts (READMEs, ADRs, design docs, diagrams, runbooks, postmortems, ERDs, etc.) from a previously-written `docs/artifacts-plan.md`. Supports two modes — **one at a time** (interview + preview/confirm + "continue?" per item, maximum oversight) and **batch** (pick a scope, interview each item, write directly, summarize at end, no per-item gates). Companion to the `artifacts-audit` skill — does NOT modify source code. Use when the user invokes `/artifacts-generate`, asks to "generate the next artifact", "execute the artifacts plan", "batch-generate this week's artifacts", "write the README / ADR / runbook from the plan", or otherwise wants to produce documented artifacts whose plan has already been audited.
---

# Artifacts generation

Companion to [[artifacts-audit]]. Reads `docs/artifacts-plan.md`, then walks through generating artifacts with the user. **Supports two modes** — the user picks upfront:

- **One at a time** — interview, preview, confirm, write, then ask *continue?* before the next. Maximum oversight. Recommended for substantive artifacts (ADRs, design docs, postmortems) where Claude's draft genuinely benefits from a review pause.
- **Batch** — pick a scope upfront (a priority tier or a custom list), interview each item, write directly, summarize all at end. Skips per-item preview-confirm and *continue?* prompts. Lower friction. Recommended for routine artifacts (CHANGELOG backfill, `.env.example`, several diagrams in one pass).

Templates for structured artifacts (ADR, runbook, postmortem) live in [reference/templates/](reference/templates/). Default paths and naming conventions are in [reference/conventions.md](reference/conventions.md).

## When this skill fires

- User types `/artifacts-generate`
- User says: "generate the next artifact", "execute the artifacts plan", "batch-generate this week's artifacts", "do all the open items", "write the README / ADR / runbook from the plan", "what's next on my artifacts list?"

## What this skill does NOT do

- **Does not autopilot, even in batch mode.** The per-item interview still happens — Claude can't write a meaningful ADR or design doc without the user's input on the decision, alternatives, and trade-offs. Batch mode skips the preview-confirm and *continue?* prompts, not the substance.
- **Does not modify source code.** Writes to `docs/` and repo-root artifact paths only (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `.env.example`, etc.). No edits to `src/`, configs, CI, or other code directories.
- **Does not skip the plan.** If `docs/artifacts-plan.md` doesn't exist, halt and tell the user to run `/artifacts-audit` first.
- **Does not mark items complete silently.** After each write, the plan gets updated in place with a status flip and a top-of-file changelog entry, both visible to the user.

## Phase 1 — Locate the plan

Read `docs/artifacts-plan.md`.

- **If missing:** stop and say: *"No artifacts plan found at `docs/artifacts-plan.md`. Run `/artifacts-audit` first to produce one, then come back."* Do not proceed.
- **If present:** parse it. Look for:
  - Status markers per item: 🟢 RECOMMENDED, ⚠️ STALE/THIN, 🟡 OPTIONAL, ✅ PRESENT, ⛔ NOT APPLICABLE
  - Priority tiers from Phase 4: `this-week`, `this-month`, `nice-to-have`
  - Per-artifact details: target path, format, effort (S/M/L), dependencies

**If all items are ✅ or ⛔:** congratulate, suggest re-running `/artifacts-audit` to refresh — the project may have grown new gaps since the plan was written. Stop here.

## Phase 2 — Choose mode & scope

### 2a. Mode

Ask the user (via AskUserQuestion) which mode they want:

- **One at a time** *(Recommended for substantive artifacts — ADRs, design docs, postmortems)* — Interview + preview/confirm + *continue?* per item. Maximum oversight.
- **Batch** *(Faster for routine artifacts — CHANGELOG, .env.example, multiple diagrams, README updates)* — Pick a scope (tier or custom list), then iterate: interview each item, write directly, summarize all at end. No per-item preview-confirm or *continue?* prompts.

If the user pre-stated a preference in their initial prompt (e.g., "batch this week's items"), skip the question and honor it. Default to **one at a time** if they say "you pick" or seem undecided.

### 2b. Scope

#### If mode = "one at a time"

Pick the highest-priority single open item by this order:

1. 🟢 RECOMMENDED in `this-week`
2. ⚠️ STALE/THIN in `this-week`
3. 🟢 RECOMMENDED in `this-month`
4. ⚠️ STALE/THIN in `this-month`
5. 🟢 RECOMMENDED in `nice-to-have`
6. Anything else still open

Present it:

```
NEXT ARTIFACT
- Name:          <e.g. ADR-0002: caching strategy>
- Status:        🟢 RECOMMENDED
- Priority:      this-week
- Target path:   docs/adr/0002-caching-strategy.md
- Format:        Markdown (ADR template)
- Effort:        S
- Justification: <one-liner from the plan>
- Dependencies:  <list, or "none">

Proceed with this one, or pick a different item?
```

Wait for confirmation. If the user picks a different item, switch to it — even if it's 🟡 OPTIONAL (flag it: *"This one's marked optional. Sure?"*).

#### If mode = "batch"

Ask the user (via AskUserQuestion) which scope:

- **All `this-week` items** *(most common)*
- **All `this-month` items**
- **All open items** (everything 🟢 or ⚠️ regardless of tier)
- **Custom list** — let the user name specific items by title

Resolve to the actual list (sorted by the priority order above), then preview it:

```
BATCH (3 items, sorted by priority)
1. ADR-0002: caching strategy        → docs/adr/0002-caching-strategy.md
2. Runbook: deploy rollback          → docs/runbooks/deploy-rollback.md
3. .env.example                      → .env.example

Each item will get its own interview, then be written directly.
Final summary at the end. No per-item confirm.

Generate all of these in sequence? (yes / change scope)
```

Wait for confirmation. Honor scope changes (remove items, add items, reorder).

## Per-item loop (Phases 3–5)

Phases 3–5 run **once per selected item**:
- In **one-at-a-time** mode: a single iteration, then Phase 6 prompts before the next.
- In **batch** mode: iterate over the full list without prompting between items.

### Phase 3 — Dependency check

If the chosen item has dependencies in the plan:

1. For each dep, check whether it's ✅ PRESENT in the plan **and** the file actually exists on disk.
2. If any dep is unmet:
   - In **one-at-a-time** mode: surface it and offer three options via AskUserQuestion — generate the dep first (recommended for hard deps), proceed anyway (acceptable for soft deps), or cancel and pick a different item.
   - In **batch** mode:
     - **Soft dep unmet:** log a one-line warning, proceed, surface it in the final summary.
     - **Hard dep unmet:** skip this item, log a one-line warning, surface it in the "Skipped" section of the final summary. Continue with the next item.

### Phase 4 — Targeted interview

Ask **2–4 focused questions** to nail down what this artifact should say. Tune the questions to the artifact type. Use AskUserQuestion for bounded choices, free-form follow-ups for open questions. **Skip any question the user already answered in their prompt.**

The interview happens **in both modes**. Walk through one item's interview at a time even in batch — don't try to front-load all interviews; that quickly becomes incoherent.

#### ADR
1. What decision is this recording? (one sentence)
2. What alternatives did you consider?
3. Main trade-off / consequence?
4. Status: Proposed, Accepted, Deprecated, or Superseded?

#### Runbook
1. What operation does this cover?
2. Trigger — alert, schedule, manual, customer request?
3. Symptoms when things go wrong?
4. Resolution sequence (rough sketch — I'll structure it)?

#### Postmortem
1. What incident? (date, name)
2. Duration and impact scope?
3. Root cause in one sentence?
4. Two highest-leverage action items?

#### Design doc / RFC / Tech spec
1. What's being built?
2. What problem does it solve?
3. Two or three design choices you want recorded?
4. Open questions still unresolved?

#### README
1. One-sentence elevator pitch?
2. Top 3 things a new user needs (install, run, troubleshoot)?
3. Audience — developers, end users, both?
4. Anything to mention upfront (license, status badge, demo link)?

#### Diagram (Mermaid / DBML)
1. What's it depicting — C4 context/container/component, sequence, state, ERD, DFD, deployment, pipeline?
2. Top 5–10 entities or components to show?
3. Key relationships or flows to emphasize?
4. Inline in another doc, or its own file?

#### CHANGELOG
1. Backfill from git history, or start fresh from today?
2. Versioning scheme — SemVer, CalVer, none?
3. Use Keep a Changelog format?

#### CONTRIBUTING
1. Who's the audience — internal team, external OSS contributors, both?
2. Key rules (commit format, branching model, review expectations)?
3. Dev setup unique enough to need its own walkthrough, or just point at the README?

#### `.env.example`
1. Should I scan the codebase for env var references and assemble the list, or are you supplying them?
2. For each var: provide a placeholder value or a one-line comment of what it is?

#### Glossary / Data dictionary
1. What's the scope — domain vocabulary, internal jargon, table/column definitions?
2. Source of truth — code, schema files, your head?

For artifact types not listed above, follow the same shape: 2–4 questions, focused on substance not boilerplate.

### Phase 5 — Draft, [confirm if single mode], write, update plan

1. **Draft** the artifact using:
   - The structured template from [reference/templates/](reference/templates/) if one exists for this type
   - The user's answers from Phase 4
   - Evidence from the repo (re-read code, config, git history, schemas — whatever's needed)
   - Default naming and paths from [reference/conventions.md](reference/conventions.md), unless the plan specifies a different path

2. **Preview & confirm** *(one-at-a-time mode only)*:
   - Show the full draft inline in chat.
   - Ask: *Write to `<path>` as-is? (yes / tweak X)*
   - Tweaks loop: if the user asks for changes, edit inline and re-show. Do not write until they confirm.
   - In **batch** mode, skip this step — emit a one-line *"Drafted: <name>"* and proceed straight to write.

3. **Write** the file:
   - Create the target directory if missing (e.g., `mkdir -p docs/adr/`)
   - Write the file via the `Write` tool
   - **Do not touch source code.** If during drafting you discover something in `src/` that needs fixing, flag it for a follow-up task — don't fix it inline.

4. **Update `docs/artifacts-plan.md` in place** *(both modes)*:
   - Flip this item's status from 🟢 / ⚠️ to ✅ PRESENT, with the new path noted.
   - Prepend a Changelog entry at the top (under existing `## Changelog`, or create one if missing):
     ```
     ## Changelog
     - YYYY-MM-DD: Generated <artifact name> at <path>. Status: 🟢 → ✅.
     ```
   - Pull today's date from the user's environment (do **not** invent it — if uncertain, ask).

The plan update happens **per item in both modes**. This way, if a batch is interrupted mid-flow, the plan reflects the actual completed state — no half-finished status.

## Phase 6 — Continue or wrap up

### One-at-a-time mode

Summarize what just happened:

```
✓ Wrote <path>
✓ Plan updated: <item> marked ✅

Remaining open items (top 3):
- <item 1> (priority: this-week)
- <item 2> (priority: this-week)
- <item 3> (priority: this-month)
```

Then offer the next:
> Generate the next item (`<next item>`)? Or stop here?

If yes → return to Phase 3 with the next item.
If no → close out: *"Stopping here. Run `/artifacts-generate` again whenever you're ready for the next one."*

### Batch mode

After each item, emit a one-line progress note as you go:

```
[2/3] ✓ Runbook: deploy rollback → docs/runbooks/deploy-rollback.md
```

After the batch finishes (or short-circuits on user interrupt), summarize in one block:

```
BATCH COMPLETE — 3/3 written
✓ ADR-0002: caching strategy        → docs/adr/0002-caching-strategy.md
✓ Runbook: deploy rollback          → docs/runbooks/deploy-rollback.md
✓ .env.example                      → .env.example

Plan updated: 3 items marked ✅.

Skipped: <list any items skipped for unmet hard deps or path conflicts, with reasons>
Warnings: <any soft-dep notes, drift, ambiguities surfaced during the batch>

Remaining open items in the plan: <count>

Want me to start another batch, switch to one-at-a-time for the rest, or review any of these?
```

If items were **skipped** in batch, list them under a `Skipped` header with the reason — never silently drop them.

## Edge cases

- **No plan file:** halt at Phase 1 and direct to `/artifacts-audit`.
- **All items ✅ or ⛔:** congratulate, suggest re-running `/artifacts-audit`. Don't loop endlessly.
- **Target path conflicts with existing file:**
  - In **one-at-a-time** mode: surface the conflict, offer three options via AskUserQuestion (overwrite, update-in-place by reading + merging, or pick a new path).
  - In **batch** mode: skip the item, list it in the final summary's `Skipped` section as *"file exists at <path>"*. The user can resolve it later in single mode.
- **Plan has no priority tiers** (manually-written or pre-Phase-4 plan): skip the priority sort. In single mode, present all open items and let the user pick. In batch mode, default the scope picker to "all open items" + custom list.
- **Two items tied for top priority** (single mode): present both, let the user pick.
- **User changes mode mid-flow:** support graceful switching.
  - Single → batch: *"actually batch the rest"* — switch from the next item onward.
  - Batch → single: *"wait, preview this one before writing"* — pause that item, do the preview-confirm, then ask whether to continue in batch or stay single.
- **Plan format has drifted** heavily: be resilient. Parse what you can. Ask the user where ambiguous rather than guessing.
- **User asks for full autopilot** (skip the interview): push back. The interview is the substance — without it, the artifacts are generic boilerplate. Offer instead: pre-write rich answers into a scratch file and pass it as context.

## Files this skill touches

- `docs/artifacts-plan.md` — updated in place **per item, in both modes** (status flips + changelog entry)
- The target path of each chosen artifact (e.g., `docs/adr/000N-*.md`, `README.md`, `docs/runbooks/<op>.md`)
- Directory creation (`mkdir -p`) where needed
- **Nothing in `src/` or other code directories.**
