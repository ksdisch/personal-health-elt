# Runbook: <Operation name>

- **Trigger:** <What initiates this — alert name, schedule, manual, customer request>
- **Severity:** <P1 | P2 | P3 | Operational>
- **Owner:** <team / role>
- **Last verified:** YYYY-MM-DD
- **Related runbooks:** <links>

## Symptoms

<What you'll see when this is happening. Be concrete — exact log lines, metric names, alert IDs, user-facing behavior. The person opening this runbook at 3 AM should be able to confirm they're in the right place within 30 seconds.>

- ...
- ...

## Pre-checks

<Things to verify before taking action. These reduce the chance of making things worse — confirm scope, confirm you have authorization, confirm you're looking at the right environment.>

- [ ] Confirm environment: prod / staging / dev
- [ ] Confirm scope: <which service / region / customer segment>
- [ ] Confirm authorization: do you have the access needed for the resolution steps below?
- [ ] ...

## Resolution

<Step-by-step. Each step should be unambiguous and copy-pasteable where possible. Number them. If a step has multiple branches based on what you see, use sub-bullets.>

1. ...
2. ...
3. ...

## Verification

<How you know it's fixed. Be specific — which metric should return to baseline, which log line should stop appearing, which user-facing check should pass.>

- ...

## Rollback

<If the resolution makes things worse, how to revert. Don't skip this section — the absence of a rollback plan is the rollback plan, and it's usually a bad one.>

- ...

## Prevention / follow-up

<What should we do so this doesn't recur, or so the runbook is needed less often? Link to an ADR or backlog item if there's structural work to do.>

- ...

## References

- **Dashboards:** <links>
- **Past incidents using this runbook:** <links to postmortems>
- **Related ADRs:** <links>
- **Source code:** <links to the relevant service/module>
