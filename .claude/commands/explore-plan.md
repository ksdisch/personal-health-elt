---
description: Explore → plan → confirm before any code. Reads the relevant code, plans without editing, proposes 2–3 ranked approaches, and waits for you to pick one before implementing. Pass the issue # or task as the argument.
argument-hint: <issue # or task description>
---

Task: $ARGUMENTS

Run the **explore → plan → confirm** loop. Do NOT write or edit any code until I
approve a plan. (If no task was given above, ask me what to work on first.)

## 1. Explore (read-only)
- Identify and read the files relevant to the task. Follow imports and call sites
  until you actually understand how the affected code works — don't skim.
- If the task references an issue number, read it first (e.g. `gh issue view <n>`).
- For broad or uncertain searches across many files, delegate to a fast **Explore
  subagent** (cheaper model) that returns conclusions — don't flood the main context
  with full-file dumps.
- Do not modify any files in this phase.

## 2. Plan (think hard — don't touch files)
- Behave as if you're in plan mode: research and reason, but make zero edits.
- Think hard about root cause / design before proposing anything. Escalate to
  `ultrathink` if the problem is genuinely gnarly.
- Produce 2–3 distinct approaches. For each: a one-line summary, the key files it
  touches, and its trade-offs (effort vs. impact vs. risk).
- Mark your recommended approach and say why.

## 3. Confirm (stop here)
- Present the approaches and STOP. Wait for me to choose one (or redirect) before
  writing a single line of code.

## 4. Code + commit (only after I pick)
- Implement the chosen approach. Stick to it; if reality diverges from the plan,
  pause and tell me rather than quietly improvising a different design.
- When it's working and verified, commit with a conventional-commit message.
  Don't push unless I explicitly say so.
