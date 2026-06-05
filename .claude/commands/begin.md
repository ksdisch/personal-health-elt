---
description: Open a session — orient on project state (branch, recent commits, open PRs), recap from the last /wrap log, offer an optional recall question, then route into the project's session-start spec (e.g., .claude/session-start.md). Project-agnostic.
---

Session begin.

Orient yourself silently. Orient me briefly. Route me into the project's
session-start flow. No filler.

## 1. Orient Claude (do this silently — don't narrate the reads)

- Re-skim `CLAUDE.md` for current phase + hard rules (already in your
  system context; just refresh)
- `git fetch origin && git status --branch`
- `git log --oneline -10`
- `gh pr list --state open --limit 10` (if `gh` is available; otherwise
  skip)
- Read `.claude/session-start.md` if it exists, or `session-start.md` at
  repo root, or any equivalent project-local "how to start a session" doc
  — this is the project's authoritative session-start spec
- Find the most recent wrap log: try `docs/session-logs/`, then
  `.claude/session-logs/`, then a quick scan for any `*session-log*` or
  dated session-recap file. If found, read it end-to-end.

## 2. Brief me — one tight block (should fit on one screen)

- Branch + tree state (clean, or what's uncommitted)
- Last 5 commits, one line each
- Open PRs that involve me — number, title, mergeable state
- If a recent wrap log was found:
  - Paste or summarize its **30-second elevator version** verbatim or
    near-verbatim
  - Cross-check current git state against the wrap's "Suggested next
    moves" and flag any drift (e.g., the wrap said PR #X was open but
    it's now merged; or the wrap said next was Y but a hotfix landed on
    main since)
- If no wrap log was found: say so in one line; don't synthesize a fake
  recap

## 3. Offer one optional recall question (single offer, accept skip cleanly)

- If the most recent wrap log has an "Active recall" section, pick **one**
  question and ask:
  > Recall question from last session: `<question>`. Answer aloud, or say
  > skip.
- If I answer: paste the matching answer-key entry from the wrap. One
  round only, then move on.
- If I say skip / no / nothing actionable: move on without comment.
- If no wrap log or no recall section: silently skip this step entirely.

## 4. Route me into the agenda

- **If a session-start spec was found**: surface the paths it defines
  (Path A, Path B, etc.) as the next choice. Mirror the file's own
  structure; don't paraphrase the paths or pick for me. Pause for my pick.
- **If no session-start spec exists**: present a minimal default — current
  branch state + top 3 backlog items (from `BACKLOG.md` if it exists,
  otherwise from `git log` against open work) + the prompt "What do you
  want to work on?" No recommendation — let me set the agenda.

## 5. Once I pick a path or name a task

- Execute the path's instructions **faithfully** (treat the path text as a
  binding spec — don't summarize it, don't shortcut steps)
- For an open-ended task: confirm a one-sentence interpretation, then
  proceed
- From this point on, `/begin` is done. You're in normal working mode.

## Tone rules

- Tight, structured, no filler. No "great question," no "let me…"
- Don't explain what you're about to do — just do it and report.
- Match my `CLAUDE.md` preferences (lists/tables/headings, concise but
  thorough, explain reasoning when asked, flag rabbit holes).
- The brief in step 2 should fit on one screen. If you need more, you
  picked the wrong altitude.
