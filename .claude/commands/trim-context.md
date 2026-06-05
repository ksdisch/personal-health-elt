---
description: Find and fix sources of Claude Code "token bloat" in a repo — oversized CLAUDE.md (vs the 40k-char limit), bloated memory files, large always-loaded files, and .claude/ cruft — then auto-apply the fixes. Optionally sweeps every repo under a parent dir. Run at a repo root, or pass a repo path / repos root.
argument-hint: [optional: a repo path, or a parent dir like ~/Projects to sweep all repos under it]
---

Target (optional): $ARGUMENTS

Audit and fix sources of per-session **token bloat**. Resolve the target: a single repo
path → just that repo; a parent dir containing multiple git repos → sweep each git repo
under it; nothing given → the current working directory's repo.

Do this for EACH repo:

## 0. Pre-flight safety (do this first — bail if unsafe)
- **Check git state** (`git -C <repo> status`, note branch + HEAD). If the repo looks like
  it's in active use by another session — HEAD/branch changed between checks, or a
  rebase/merge/lock in progress — **STOP and report**. Never do git surgery in a repo
  something else is mutating.
- **Never switch the user's branch, stash, or reset their uncommitted work.** If the tree is
  dirty, work on the current branch and stage only the files you change; create a fresh
  branch only when the tree is clean.
- Best run **inside the target repo's own session** (so it sees live state + existing docs).
  Reaching in from another repo's session is the failure mode that trips on dirty trees and
  concurrent edits.

## 1. Measure (read-only, cheaply)
Get sizes the cheap way — `wc -c`, `ls -la`, `git ls-files` — **don't read whole files
into context just to measure**; only read a file in full in step 2 when you're about to
edit it. Report a short before-snapshot with hard numbers:
- **CLAUDE.md size** — char count vs the **40,000-char** limit (Claude Code warns past
  it). Check the repo CLAUDE.md and any nested ones. Over ~25k is heading toward trouble;
  over 40k is a definite fix.
- **Memory bloat** — total size of the project's memory dir (`MEMORY.md` + entries) if
  present; flag oversized, stale, or duplicate entries.
- **Large always-loaded files** — anything CLAUDE.md pulls in via `@`-references, or
  obviously huge docs that load into context every session.
- **.claude/ cruft** — orphaned/duplicate commands, skills, agents, or notes.

## 2. Fix (auto-apply — don't just recommend)
- **Slim CLAUDE.md to a lean, always-true core.** Keep the rules Claude needs *every*
  session (conventions, hard do/don'ts, key commands, file layout). Move stable detail
  that's only *sometimes* needed (long gotcha lists, historical context, deep
  walkthroughs) OUT into linked docs under `docs/` (or a skill), and reference them from
  CLAUDE.md by path so they load on demand instead of every turn. **Never delete a rule —
  relocate it and leave a pointer.**
- **Reuse existing offload docs.** Before creating `docs/ARCHITECTURE.md` (etc.), check
  whether one already exists — it often does. Append/merge into it rather than duplicating or
  clobbering, and namespace new extracts (e.g. `docs/claude/`) if names would collide.
- **Trim memory** — merge duplicates, delete stale/incorrect entries, tighten verbose
  ones; keep `MEMORY.md` to one tight line per memory.
- **Prune .claude/ cruft** you're confident is dead; for anything ambiguous, list it for
  me rather than deleting.
- Preserve meaning everywhere — this is about *where* context lives and *when* it loads,
  not discarding information.

## 3. Verify & commit
- Re-measure and show before→after (e.g. "CLAUDE.md 58.6k → 18.2k chars").
- **Interactive/manual run:** commit the fixes in place (conventional commit, this repo's
  style). Don't push unless I say so.
- **Unattended/scheduled run:** open a PR instead of committing to a working branch, so a
  human reviews before it lands. Never auto-merge.
- Stage only the files you changed — never `git add -A`; the tree may hold other work. Do
  NOT switch branches, stash, or reset the user's uncommitted work.

## 4. Report
Per repo: before→after numbers, what you moved/trimmed/relocated (and where), anything you
left for me to decide, and the commit/PR link. When sweeping multiple repos, end with a
one-line-per-repo summary.
