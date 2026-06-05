---
description: With a target → autonomously plan/build/test/verify it end-to-end and report. With NO target → triage your backlog into ranked candidates (pros/cons/heuristic blast radius/logic), let you pick one or launch a collaborative brainstorm for something new, then build the choice autonomously. Uses ultracode multi-agent orchestration.
argument-hint: [optional target; omit to triage the backlog / brainstorm]
---

Target (optional): $ARGUMENTS

You are running an autonomous milestone workflow. **Use multi-agent orchestration — the
Workflow tool — for the fan-out steps.** This command is your explicit opt-in to ultracode;
you do not need to ask permission to orchestrate.

First, orient on THIS project — don't assume a stack. Read `CLAUDE.md`, any
backlog/roadmap/plan/TODO docs, `README`, and recent git history. Adapt to its conventions,
test/build commands, and definition of "done."

## Route
- **Target given above** → skip selection entirely; go straight to **Build**.
- **No target** → run **Select** (backlog triage → optional brainstorm) to land on a
  milestone, then **Build** it.

## Token discipline — spend by phase, don't dull quality
- **Select / triage = LIGHT.** Small subagent team on cheap/fast models (`haiku`/`sonnet`)
  for listing, ranking, and per-candidate notes; heuristic blast radius (no deep code reads).
  This is the common path — keep it cheap.
- **Brainstorm = HEAVY, and only if I ask for it.** The full multi-agent adversarial rig,
  `opus` for idea-generation + verification.
- **Build = as needed.** Tier subagents (cheap for explore/scan/mechanical, `opus` for
  architecture + verification), bound the fan-out, keep the main thread lean (subagents
  return conclusions; write plan + report to files), and `/compact` at seams.

---

## Select  (no target given) — find the milestone

### 1. Backlog triage  (LIGHT — small/cheap team)
- **Auto-discover the backlog:** scan `BACKLOG.md` + any roadmap/plan/TODO/`docs/*` planning
  files, AND open GitHub issues (`gh issue list`, if `gh` + a remote are available). Merge and
  dedupe into one candidate set.
- Present **as many candidates as make sense** — not capped at 3 (could be 3, could be 10).
  For EACH, give the case:
  - one-line what-it-is
  - **pros** / **cons**
  - **blast radius** — a quick *heuristic* (which areas/files it likely touches, rough risk);
    do NOT deep-read code for every candidate
  - the **logic** for doing it + rough impact-vs-effort
- Rank by your best impact/effort/risk read.

### 2. Let me choose
Present the ranked candidates (AskUserQuestion) **plus an explicit
"None of these — brainstorm something new" option.**
- I pick a candidate → **now deep-dive that one's blast radius** (read the relevant code to
  firm up scope/risk for the chosen item only) → go to **Build**.
- I pick "brainstorm something new" → go to **Brainstorm**.

### 3. Brainstorm  (only if I chose it — HEAVY rig)
- **Interview first (just you + me — no fan-out yet):** a few focused questions to surface
  what *kind* of change/update/goal I'm after (user-facing vs foundation vs polish vs perf;
  appetite/scope; constraints). Get me thinking.
- **Confirm the direction with me** before spending on the fan-out.
- **Then the heavy machinery:** many subagents exploring the confirmed direction in parallel,
  building on each other, with adversarial review/critique rounds to sharpen and kill weak
  ideas.
- Present the results in the same "case" format (pros/cons/heuristic blast radius/logic).
  I pick one → deep-dive its blast radius → go to **Build**.

---

## Build  (target given, OR a candidate chosen) — autonomous, no further gate

Giving a target / picking a candidate **is** the go-ahead. Do NOT stop for plan approval —
plan, build, test, verify, and report autonomously.

1. **Plan.** Produce a concrete, sequenced implementation plan (including prereqs/cleanups
   surfaced during selection); write it to a plan doc in the repo so progress is trackable.
   **Prereqs are not blockers — fold the groundwork in.**
2. **Build.** Feature branch first. Implement in sequenced, committed steps (conventional
   commits matching the project's style). Multi-agent where work parallelizes.
3. **Test & verify — yourself.** Run tests/typecheck/build. For anything you'd normally hand
   me — manual smoke tests, clicking the running app, dashboards, DB/SQL consoles (e.g.
   Supabase) — do it autonomously with the tools available: the `kapture` browser MCP,
   `computer-use`, Playwright/Puppeteer. Drive the real UI and real consoles yourself.
4. **Self-correct.** Iterate until it genuinely works: tests green, build clean, feature
   verified end-to-end against the running app. Adversarially check your own work before
   declaring done.

### Autonomy boundary (hard limits)
- ✅ **Without asking:** branch, commit, push, open a PR, run migrations on
  **local / dev / staging**, drive UIs and consoles via tools.
- ⛔ **Never without explicit go-ahead:** **merge to `main`**, and any write to **production**
  data/services or other destructive/irreversible action — stop and report.
- A true blocker you can't resolve with available tools (missing credential, external
  approval, ambiguous product call) → stop and ask, but exhaust your tools first.

### Report back
When complete (or you've opened the PR / hit a boundary), report: what you built, the branch +
PR link, what you tested and how (including the autonomous smoke-tests/console work), anything
skipped and why, and any decisions I should review. This report should be the only thing I need
to read to know what happened.
