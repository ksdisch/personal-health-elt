---
name: artifacts-audit
description: Audit a codebase to determine which canonical engineering artifacts (READMEs, ADRs, design docs, diagrams, runbooks, postmortems, ERDs, etc.) it should have on file, then propose a concrete generation + maintenance plan. Runs a 5-phase discovery → profile → audit → plan → deliverable flow and writes the result to `docs/artifacts-plan.md`. Plans only — does not generate the artifacts themselves and does not modify source code. Use when the user invokes `/artifacts-audit`, or asks to audit / inventory / plan a repo's documentation, diagrams, ADRs, runbooks, or other engineering artifacts.
---

# Engineering artifacts audit

Audit the current codebase against a canonical taxonomy of engineering artifacts (docs, diagrams, plans, ops material, knowledge) and produce a single planning document plus a chat summary. This skill **plans only** — generation is a follow-up session.

The canonical taxonomy is in [reference/taxonomy.md](reference/taxonomy.md). Skim it before Phase 3.

## When this skill fires

- User types `/artifacts-audit`
- User asks something like: "audit this repo's docs", "what artifacts should this project have?", "plan engineering documentation", "what's missing from this codebase's documentation?", "inventory our ADRs / diagrams / runbooks"

## What this skill does NOT do

- **Does not modify source code.** Hands off on `src/`, configs, CI, etc.
- **Does not generate the artifacts themselves** (no READMEs, ADRs, diagrams written this session). That's the follow-up.
- **Does not skip Phase 2.** The project profile + pause for confirmation is the load-bearing step. Don't shortcut it.
- Creating `docs/artifacts-plan.md` and the `docs/` directory IS allowed — that's the deliverable.

## Phase 1 — Discovery

Explore the repo systematically. Use the most efficient tool for each step (Bash for `git`/`find`, Glob/Grep for surveys, Read for files). If the repo is large or unfamiliar, dispatch the Explore subagent for the broader sweeps. Minimum work:

1. **Inventory the tree.** Top-level files + directories (3 levels deep), language breakdown, total file count.
2. **Read entry points.** README, package manifest (`package.json`, `pyproject.toml`, `requirements.txt`, `go.mod`, `Cargo.toml`, `Gemfile`, etc.), `Makefile`/`Taskfile`, `Dockerfile`, `docker-compose.yml`, infrastructure config (Terraform, k8s manifests).
3. **Sample the source.** Main entrypoint(s), the largest source files, and a representative test file. Skim the directory structure to infer architecture.
4. **Check existing docs.** Anything in `/docs`, `/doc`, `/.github`, top-level `*.md` files. Inventory what's already there and assess freshness — is the README accurate? Does CHANGELOG match recent tags?
5. **Read git history.** `git log --oneline -50`, `git log --stat -10`, recent branches, contributor count. Note frequency and what's actively changing.
6. **Detect the stack.** Languages, frameworks, datastores, orchestrators (Prefect / Airflow / dbt / etc.), CI provider, deployment target, observability.
7. **Detect the project shape.** Library, application, service, data pipeline, CLI, monorepo, infrastructure repo, research/notebook, ML training, or hybrid.

## Phase 2 — Project profile (STOP and present)

After Phase 1, produce this profile in chat and **pause for confirmation**:

```
PROJECT PROFILE
- Shape: <library | service | data pipeline | CLI | infra | monorepo | ...>
- Primary language(s): ...
- Stack: ...
- Datastores: ...
- Deployment / orchestration: ...
- Audience: <internal only | public/OSS | portfolio | client work>
- Maturity: <prototype | active dev | production | maintenance>
- Team size: <solo | small team | many contributors>
- Active areas (from recent git): ...
- Existing docs/diagrams: ...
- Notable gaps observed: ...
- 3 sharpest open questions before I can recommend confidently: ...
```

**Wait for the user to confirm or answer.** Only then proceed to Phase 3.

## Phase 3 — Audit & recommendation

For every artifact in [reference/taxonomy.md](reference/taxonomy.md), classify as:

- ✅ **PRESENT** — exists and is in reasonable shape (note location + brief quality assessment).
- ⚠️ **STALE/THIN** — exists but outdated, incomplete, or low quality.
- 🟢 **RECOMMENDED** — missing; this project would clearly benefit; propose generating it.
- 🟡 **OPTIONAL** — would be nice but not high-leverage given this project's shape/audience.
- ⛔ **NOT APPLICABLE** — doesn't fit this project (e.g., wireframes for a backend CLI).

For every ✅, ⚠️, and 🟢, give a **one-line justification tied to SPECIFIC evidence from Phase 1** — the actual stack, actual decisions visible in the code, actual operational realities, actual gaps. Generic SaaS-blog justifications are not useful. If you wouldn't say "because of X in this repo", don't say it.

Present the audit as **one table sorted by category**.

## Phase 4 — Generation & maintenance plan

Propose a concrete plan with five components:

1. **Priority order.** Three tiers — `this-week` / `this-month` / `nice-to-have` — sorted by leverage-to-effort ratio. For a portfolio repo, weight credibility signal high; for a production service, weight operational risk high.

2. **Per artifact.** Target path, suggested format (Markdown / Mermaid / DBML / etc.), estimated effort (S / M / L), and dependencies (e.g., "design doc needs ADRs 1–3 first"; "ERD needs final schema").

3. **Maintenance cadence.** When each artifact gets refreshed:
   - **Per-PR:** README, inline architecture diagram (when touched), CHANGELOG entry
   - **Per-release:** CHANGELOG finalization, version bump
   - **Per-significant-decision:** new ADR (numbered, append-only)
   - **Per-incident:** postmortem from template
   - **Quarterly:** roadmap, backlog grooming, runbook re-verification dates
   - **Triggered:** ERD when schema changes, architecture diagram when topology changes, data dictionary when models change

4. **Suggested automation.** Practical CI / dev-loop helpers — e.g., a link-checker workflow, `dbt docs generate` in CI, a Mermaid lint step, conventional-commits → auto-CHANGELOG, a pre-commit hook to enforce ADR numbering.

5. **Naming conventions & structure.** Concrete paths:
   - `docs/adr/000N-short-title.md`
   - `docs/design/<feature>.md`
   - `docs/runbooks/<operation>.md`
   - `docs/diagrams/<name>.mmd` or inline in Markdown
   - `docs/postmortems/YYYY-MM-DD-<incident>.md`
   - Adjust if the repo already has an existing convention.

## Phase 5 — Deliverable

Write the entire audit + plan to `docs/artifacts-plan.md` (create the `docs/` directory if needed). **If `docs/artifacts-plan.md` already exists, update it in place and note what changed at the top.** This file becomes the source of truth for the follow-up generation session.

Then summarize in chat:

- The **3–5 highest-leverage artifacts to generate next**, in order.
- Any **decisions the user needs to make before generation can start** (open questions from Phase 2 that resurfaced, plus new ones).
- A **suggested next prompt** to kick off generation (one or two sentences the user can paste back).

## Constraints

- **Do not modify source code.**
- **Do not generate the actual artifacts** (READMEs, ADRs, diagrams) in this session. Plan only.
- Creating `docs/artifacts-plan.md` and the `docs/` directory IS allowed — that's the deliverable.
- **Anchor every recommendation to specific repo evidence.** If you can't, flag it as an open question rather than guessing.
- **Be honest about uncertainty.** "Unclear from the repo whether X is needed" is a valid finding.
- **Match formality to audience.** A personal portfolio repo does NOT need OKRs or RACI; a production team service might. A solo prototype does NOT need a CONTRIBUTING.md.
- **Default diagram format: Mermaid.** Reach for DBML (ERDs in DB-heavy repos), Excalidraw (lo-fi sketches), or Figma (UI) only when justified.
- **Keep the plan executable** — every recommendation needs a clear path, target location, and effort estimate.

## Files this skill touches

- `docs/artifacts-plan.md` — the deliverable (created or updated in place).
- `docs/` — created if missing.
- Nothing else. No source code modifications.
