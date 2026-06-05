---
description: Generate a self-contained handoff prompt I can paste into a fresh Claude Code session to continue this work without losing context. Captures hard-won lessons, what's done, and where the plan stands. Stops the current work after generating. Project-agnostic.
---

Context handoff.

I'm stopping here to switch to a fresh Claude Code session. Generate a
self-contained prompt I can paste into a new session so it picks up exactly
where we left off — no rediscovery, no repeated mistakes, no preamble.

Write for a fresh AI session, not a human reader. The fresh session has zero
memory of this conversation but has the same file/git access. Include only
what the fresh session cannot derive from `git status`, `git log`,
`gh pr list`, or reading the repo cold. Skip anything obvious from those.

## Before writing — orient silently

- `git status --branch` and `git log --oneline -10` to confirm the current
  branch/tree state and recent commits this session produced
- `gh pr list --state open --limit 10` if `gh` is available
- Re-skim any plan / source-of-truth file the session has been working from
  (e.g. `docs/<topic>-plan.md`, `BACKLOG.md`, an open PR body) — the fresh
  session will need its path
- Mine THIS conversation for landmines: hooks that blocked, commands that
  failed and then worked, decisions made, things the user explicitly said
  "do/don't do." These are the hard-won lessons. They are not in git.

## Output format

Print the handoff as a single fenced code block so I can copy it verbatim.
Do not narrate before or after the block. After printing, **STOP** — do not
continue the current work and do not ask "what's next." I'll start a fresh
session.

Match my CLAUDE.md preferences: structured, concise but thorough, no filler,
name tradeoffs, quote exact paths/branches/PRs/commands rather than
paraphrasing.

## Handoff structure (sections, in order, inside the code block)

1. **Title** — `# Context handoff — <project>: <one-line topic>`

2. **Overview (2–4 sentences)** — what the project is in plain language,
   what's being continued, and the source-of-truth doc/file the fresh
   session should read first. Name the plan file and say what role it plays
   (e.g. "tracks status in a `## Changelog` section at the top").

3. **What's done** — terse bullets of work completed this session. Quote
   exact PR numbers, commit refs, file paths, branch names. Group by PR or
   branch if multiple are in play. Artifacts only, no subjective spin.

4. **Hard-won lessons (apply these)** — the most important section after the
   plan-stands one. Capture gotchas, workarounds, and conventions discovered
   THIS session that a fresh session would otherwise re-hit. Each bullet:
   - Quotes the exact command, file path, hook name, or error message
   - Frames as "X is the case; do Y" or "Z breaks; the path that works is …"
   - Examples worth capturing: pre-commit/push hooks that block direct push,
     repo-specific merge workflow (squash vs merge, branch naming, base
     branch), tools/CLIs the repo expects, env vars that must be set, files
     whose contents look authoritative but aren't, decisions already made
     under uncertainty (so the fresh session doesn't relitigate them),
     things I explicitly told you to do or not do
   - Skip generic advice — only session-specific landmines

5. **Where the plan stands** — the load-bearing section. Be specific:
   - What's in progress right now (file, branch, PR, line of work)
   - The next concrete action, as one imperative sentence
   - What's blocked and on what
   - Any decisions pending me — mark these clearly so the fresh session
     asks before acting, doesn't assume
   - The 1–3 files/branches/PRs the fresh session should open first

## Length

A few hundred words is normal. If the handoff is creeping past ~600 words,
you're including things derivable from git — cut those. If it's under ~150
words, you're probably missing the hard-won lessons — mine the conversation
harder.

## Honesty rules

If something is half-done or wrong, say so. If a decision was made under
uncertainty, flag the assumption so the fresh session can revisit. Don't
paper over gaps to make the handoff look tidy — gaps are exactly what the
fresh session needs to know about.
