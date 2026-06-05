---
description: End-of-session wrap-up that recaps the work, explains the why, builds vocabulary, quizzes via active recall, and suggests next moves. Saves to a dated file and prints to chat. Project-agnostic.
---

Session wrap-up.

I'm ending this session. Generate a wrap-up artifact that helps me (a) retain
the substance of what we did, (b) build the vocabulary and mental models to
discuss it fluently — casually with a friend or in a technical interview —
and (c) know what's worth doing next.

Write as an experienced developer briefing a peer who has never seen this
project. Tight, concrete, no flattery. Match my preferences from CLAUDE.md
(structured output, concise but thorough, explain reasoning, name tradeoffs,
flag rabbit holes). Work from observable state — `git log`, the conversation,
files on disk. Don't invent.

Save the wrap-up to a dated file. Pick a sensible path based on existing
project conventions; default to `docs/session-logs/YYYY-MM-DD-<project>-<short-slug>.md`
if no convention exists. `<project>` = a short tag for the current project
(2–6 chars, lowercase, kebab-case) so logs from different projects are
distinguishable at a glance in a recents list. Derive it from the git repo
name or the working directory basename; abbreviate if long (e.g.
`job-search-toolkit` → `jst`, `cowork-second-brain` → `csb`). Slug = a 3–5
word summary of the session's primary work. Don't dump the full wrap-up
into chat — I'll read it from the file. In chat, just print the saved path
and a one-line confirmation.

As the final step, open the saved file so I don't have to open it manually:
run `open <path-to-file>` via Bash.

Sections, in this order:

1. **What we did** — 3–8 bullets, factual, one line each. Concrete artifacts
   only (PRs, commits, files, decisions). No subjective spin.

2. **The why** — for each non-trivial change or decision, 1–3 sentences:
   what problem it solves, what alternative (if any) was rejected, what
   tradeoff was taken. Name the pattern or principle if one applies
   (e.g., "server-side validation over client trust", "additive migration
   not destructive", "RLS-as-default", "feature flag gated rollout").

3. **Concepts and vocabulary** — 5–10 entries. Every meaningful technical
   term that showed up gets a one-line definition plus a one-line anchor
   to where it appeared today. If a term has a more common industry name,
   list both.

4. **Takeaways** — 2–4 portable lessons. Patterns or mental models from
   today that generalize to other code or other projects. Phrase as a rule
   of thumb + one-line example from today.

5. **Suggested next moves** — 2–4 candidates, prioritized. Each gets: what
   it is, why it's a reasonable next pick (reasoning from project state,
   dependency order, blast radius, or strategic value), and rough effort.
   Mark one "(Recommended)" with the reasoning behind the pick.

6. **30-second elevator version** — a single ~4–6 sentence paragraph I
   could speak aloud if asked "what did you work on today?" or "what's that
   project doing right now?" Compressed but specific. Sound spoken, not
   written. This is the interview-prep deliverable.

7. **Active recall** — 3–5 questions an interviewer might ask about today's
   work ("Can you walk me through how X works?" / "Why did you pick A over
   B?" / "What would break if Y wasn't there?"). List the questions first.
   Then a separator and the line: "Try to answer each aloud before
   scrolling. Answer key below." Then the answer key as a separate
   subsection. Do not interleave questions and answers.

Scaling: if the session covered very little (one trivial change), shrink
each section proportionally — don't pad. If the session covered a lot,
prioritize the load-bearing decisions over the small stuff.

Honesty rules: name tradeoffs. If we punted on something, say so. If
something is half-done or has known gaps, flag it. Don't recap things
that already exist in CLAUDE.md or the backlog unless they changed today.
