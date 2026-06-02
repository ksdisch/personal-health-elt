# ADR-0003: Two-level idempotency — SHA file ledger + row-level ON CONFLICT, one transaction

- **Status:** Accepted
- **Date:** 2026-04-23
- **Deciders:** Kyle Disch (solo, AI-assisted)
- **Related:** ADR-0004 (the weekly flow that relies on re-runnable loaders), `ingest/loaders/quantities.py`, `scripts/init_raw_schema.sql`

## Context

Apple Health re-exports contain the **full history** every time, not a delta. The
weekly ingest will therefore re-encounter the same files and the same rows
repeatedly. Without idempotency, every run inflates `raw.*` with duplicates,
breaks the natural-key assumptions downstream, and makes "just re-run it" a
dangerous operation rather than a safe one. Because the flow is scheduled and
laptop-bound (ADR-0004), partial/interrupted runs are a normal occurrence — a
loader that half-writes a file's rows and then dies must not leave the warehouse
in a corrupt state.

We need re-running any loader on any input to be a provable no-op when nothing
changed, and a clean partial-completion when only some files are new.

## Decision

Idempotency is enforced at **two levels inside a single transaction**:

1. **File level** — a SHA256 of each file's bytes is checked against
   `raw.file_inventory`. If the hash is present, the file is skipped entirely
   before any row work.
2. **Row level** — surviving rows are inserted with `ON CONFLICT (natural key)
   DO NOTHING`, so overlapping rows across files (or a changed file that shares
   rows with a prior one) never duplicate.

The file-inventory insert and the row inserts commit in the **same**
`engine.begin()` transaction. A failure anywhere rolls back *both* — the file is
not marked consumed unless its rows landed, so a retry re-processes it cleanly.

## Alternatives considered

- **File-hash ledger only** — rejected: a file that is re-exported with one new
  day appended has a new hash, so the whole file re-loads; without row-level
  `ON CONFLICT` the overlapping days duplicate.
- **Row-level `ON CONFLICT` only** — rejected: works for correctness but forces
  every run to parse and attempt-insert every row of every file, even fully-seen
  files. The file ledger short-circuits seen files cheaply.
- **Separate transactions for ledger vs. rows** — rejected: opens a window where
  the file is marked consumed but its rows failed (or vice versa), which is the
  exact corruption idempotency is meant to prevent.
- **Truncate-and-reload each run** — rejected: throws away derived state, is slow
  on full history, and is unsafe if a run is interrupted mid-truncate.

## Consequences

**Positive:**
- "Re-run it" is always safe — the headline operational property the whole
  scheduled pipeline (ADR-0004) depends on.
- Seen files cost a single hash lookup, not a full parse.
- Partial runs are clean: only genuinely-new files commit.

**Negative:**
- Every loader must thread both mechanisms and share one transaction — enforced
  by convention and shared helpers, not by the type system. New loaders must
  follow the pattern deliberately.

**Neutral but worth noting:**
- A real bug surfaced under this design and was fixed: pandas `NaN` in object
  columns lands in Postgres `TEXT` as the literal string `"NaN"` unless coerced
  to `None` at the record boundary. Caught by running on real data.

## References

- `ingest/loaders/quantities.py` — both levels inside `engine.begin()`.
- `scripts/init_raw_schema.sql` — `raw.file_inventory` and the natural-key PKs.
- CLAUDE.md → "Loaders MUST be idempotent".
