# Postmortem: <Incident name>

- **Date:** YYYY-MM-DD
- **Duration:** <start time → end time, total minutes/hours>
- **Severity:** <P0 | P1 | P2>
- **Authors:** <names>
- **Status:** Draft | Under review | Final
- **Related:** <links to incident ticket, Slack thread, runbook used>

## Summary

<2–4 sentences. What happened, what was the impact, what was the root cause, how was it resolved. Should be readable standalone — someone scanning postmortems six months from now should understand the gist without scrolling.>

## Impact

- **Users affected:** <how many, what segments>
- **Functional impact:** <what stopped working — be specific>
- **Revenue / SLA impact:** <if measurable>
- **Internal impact:** <on-call paged, weekend work, customer-support escalations, etc.>

## Timeline

<UTC times. One line per material event — first signal, first human response, root cause identified, mitigation applied, all clear. Resist the urge to include every minor message; only events that mattered to the response.>

- **HH:MM** — Deployment of #1234 begins.
- **HH:MM** — First alert fires (`HighErrorRate` on `api-gateway`).
- **HH:MM** — Engineer paged via PagerDuty.
- **HH:MM** — Engineer joins incident channel.
- **HH:MM** — Root cause hypothesized (deploy regression).
- **HH:MM** — Rollback initiated.
- **HH:MM** — Error rate returns to baseline.
- **HH:MM** — All clear confirmed across regions.

## Root cause

<The real "why this happened" — not just the proximate trigger but the underlying systems/process gap. Five whys is a useful structure if the cause isn't obvious. Two paragraphs max — if it takes more, you may be conflating multiple causes; consider whether this is really one incident or several.>

## What went well

<Be generous here — practices that worked deserve to be reinforced. "We caught it within 4 minutes via the new alert" is worth recording.>

- ...

## What went poorly

<Be honest. "The on-call alert routed to the wrong team" is uncomfortable but actionable. Aim at systems and processes, not people.>

- ...

## Where we got lucky

<Don't skip this section — it surfaces fragility that wasn't tested by this incident. "If the bug had hit during peak hours instead of Sunday morning, the impact would have been 10x." That's the kind of thing that becomes a future P0 if you don't write it down now.>

- ...

## Action items

<Concrete, owned, dated. Use the type column to balance the portfolio — too many "Prevent" items and not enough "Detect" / "Mitigate" suggests you're papering over a deeper issue.>

| # | Action | Owner | Due | Type |
|---|--------|-------|-----|------|
| 1 | ... | ... | YYYY-MM-DD | Prevent / Detect / Mitigate / Process |
| 2 | ... | ... | YYYY-MM-DD | ... |
| 3 | ... | ... | YYYY-MM-DD | ... |

## Lessons

<Patterns to remember, not item-level fixes. What does this incident teach us about the system, the team, or how we operate? Aim for things future-you will reread and nod at.>

- ...

## References

- <Incident ticket / chat thread>
- <Related ADRs, runbooks, design docs>
- <Code or config commits involved>
