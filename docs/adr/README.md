# Architecture Decision Records

Numbered, append-only records of hard-to-reverse decisions in `personal-health-elt`.
Format: MADR-lite (see any file). New decisions get the next number; superseded
decisions are marked `Superseded by ADR-NNNN` rather than rewritten.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-timezone-normalization-at-staging.md) | Normalize timezones to America/Chicago at the staging layer only | Accepted |
| [0002](0002-multi-source-dedup-priority.md) | Multi-source dedup priority — Apple Watch > iPhone > third-party | Accepted |
| [0003](0003-two-level-idempotency.md) | Two-level idempotency — SHA file ledger + row-level ON CONFLICT, one transaction | Accepted |
| [0004](0004-self-hosted-prefect-over-gha-launchd.md) | Self-hosted Prefect (`flow.serve` under launchd) over GitHub Actions cron | Accepted |
| [0005](0005-mart-recovery-state-public-api.md) | Treat `mart_recovery_state` as a versioned public API with lockstep consumers | Accepted |
| [0006](0006-pure-sql-holt-forecasting.md) | Pure-SQL Holt's-method forecasting (no Python ML dependency) | Accepted |
| [0007](0007-dbt18-nested-accepted-values.md) | Use the dbt 1.8+ nested `arguments:` form for `accepted_values` tests | Accepted |
