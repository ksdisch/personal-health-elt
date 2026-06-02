# ADR-0002: Multi-source dedup priority — Apple Watch > iPhone > third-party

- **Status:** Accepted
- **Date:** 2026-04-24
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0001 (same staging window), `transform/models/staging/stg_quantities.sql`

## Context

The same physiological metric is frequently recorded by more than one device at
overlapping times. A heart-rate reading can come simultaneously from the Apple
Watch (chest-adjacent PPG, continuous) and the iPhone (less reliable, often a
manual or app-relayed sample); a step count can be double-counted across both.
If staging passes all of them through, daily marts double-count or average across
sources of unequal quality, and `unique(day)` contracts on the daily marts break.

We need a deterministic winner per `(metric, timestamp)` — not an average, because
averaging a high-quality Watch reading with a noisy phone reading degrades the
better signal. The choice of winner must be stable (same inputs → same output) so
re-runs are reproducible.

## Decision

In staging we assign a `source_priority` (1 = Apple Watch, 2 = iPhone,
3 = other/third-party) and keep only the rank-1 row per natural key via
`row_number() over (partition by metric_name, start_ts order by source_priority)`,
filtered to `= 1`. Apple Watch wins, iPhone is the fallback, third-party apps are
last. This runs in the same staging models as the TZ normalization (ADR-0001),
once, before any aggregation.

## Alternatives considered

- **Average across sources** — rejected: blends a trustworthy sensor with a noisy
  one; the result is worse than the Watch reading alone.
- **Keep all sources, dedup in each mart** — rejected: duplicates the partition
  logic across 17 marts and re-opens the door to inconsistent results; the
  `unique(day)` contract would have to be enforced 17 times instead of once.
- **Trust the export's own dedup** — rejected: the Simple Health Export CSV
  contains overlapping per-source rows; there is no upstream dedup to rely on.
- **Priority by recency (latest sample wins)** — rejected: recency is uncorrelated
  with quality here; a late phone sample would beat an earlier Watch sample.

## Consequences

**Positive:**
- Deterministic, reproducible winner per metric per timestamp.
- The highest-quality sensor is preserved intact rather than diluted.
- Daily marts can safely assert `unique(day)` — dedup already happened upstream.

**Negative:**
- The priority order is encoded as a fixed mapping in staging. A new primary
  device (e.g. a future ring/strap that should outrank the Watch) requires editing
  the `source_priority` CASE, not config. Accepted as a rare event.

**Neutral but worth noting:**
- Priority is by *device class*, not by individual device name, so a replacement
  Apple Watch inherits rank 1 automatically.

## References

- `transform/models/staging/stg_quantities.sql` — the `row_number()` window.
- CLAUDE.md → "Multi-source dedup priority".
