---
name: new-loader
description: Scaffold a new idempotent Apple Health ingest loader under ingest/loaders/, pre-wired to this project's two-level idempotency contract (SHA file-ledger skip + row-level ON CONFLICT in a single transaction) and the multi-source dedup-at-staging rule. Use when adding a new HealthKit metric type, a categories-style loader (sleep stages, mindfulness), or any new raw landing path. Walks the five wiring points (loader, batch dispatch, raw DDL, staging model, pytest) so a new loader starts correct.
disable-model-invocation: true
---

# new-loader — scaffold an idempotent HK loader

Scaffold a new loader that lands an Apple Health CSV into `raw.*` **idempotently**.
The #1 non-negotiable in this repo: re-running a load on the same file MUST be a
no-op — no duplicates, no partial writes. Mirror the existing loaders; do not
invent a new shape.

Read these before writing — they are the source of truth, this skill only
orchestrates them:
- `ingest/loaders/categories.py` — the canonical loader to mirror.
- `ingest/loaders/_idempotency.py` — the shared `already_loaded` / `record_file`
  / `upsert_rows` / `records_with_none_for_nan` helpers. **Always reuse these;
  never hand-roll the upsert.**
- `ingest/loaders/batch.py` — the dispatch table the folder loader walks.
- `scripts/init_raw_schema.sql` — where the raw table DDL lives.
- `.claude/agents/loader-engineer.md` — the deeper contract notes.

## Step 0 — gather inputs

Ask the user (one at a time if unspecified):
1. **Metric type** and a short name (`<type>`, snake_case) — e.g. `respiratory`.
2. Is it a **quantity** (single numeric `value` + `unit`) or a **category**
   (discrete/state rows like sleep stages)? This picks which existing loader to
   mirror (`quantities.py` vs `categories.py`).
3. The **natural key** for ON CONFLICT. Default for quantities:
   `(metric_type, source_name, start_ts)`; for categories:
   `(category_type, source_name, start_ts)`. Confirm there's no finer-grained
   collision (e.g. two samples at the same start_ts from one source).

## The idempotency contract (bake this in — do not deviate)

Two levels, both inside **one** `engine.begin()` transaction so a failed insert
rolls back the file-inventory row and the next run reprocesses cleanly:

1. **File-level (SHA256 ledger).** `hash_file(path)` → if `already_loaded(conn,
   sha)` returns true, skip the whole file. After a successful parse,
   `record_file(conn, sha, path.name)`.
2. **Row-level (ON CONFLICT DO NOTHING).** `upsert_rows(conn, df, table=...,
   index_elements=[<natural key>])`. It returns the true inserted-row delta.

Two more rules that live OUTSIDE the loader:
- **Multi-source dedup is a staging concern, not the loader's.** Loaders are
  dumb — land every source's rows. The Apple Watch > iPhone > third-party winner
  is picked by a `row_number()` window in `stg_<type>.sql`. Do NOT filter sources
  in Python.
- **NaN → None at the boundary.** pandas NaN in object columns lands in TEXT as
  the literal string `"NaN"` unless coerced. `upsert_rows` already calls
  `records_with_none_for_nan`; if you build records yourself, coerce explicitly.

## Step 1 — the loader (`ingest/loaders/<type>.py`)

Mirror `categories.py`: a `parse_<type>_csv(path)` that strips the optional
`sep=,` hint line, renames the HK camelCase columns to snake_case, raises on
missing required columns, tolerates missing optionals (land as `pd.NA`), and
parses timestamps as **UTC-aware** (`pd.to_datetime(..., utc=True)`); then a
`load_<type>_csv(path, engine=None)` that runs the two-level contract above and
returns a frozen `LoadResult` dataclass. Keep the `_main()` CLI shim.

Skeleton (fill in columns / required set / natural key):

```python
"""Loader for Apple Health <type> metrics. Lands rows in raw.<type>."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from ingest.db import get_engine
from ingest.file_inventory import hash_file
from ingest.loaders._idempotency import already_loaded, record_file, upsert_rows

logger = logging.getLogger(__name__)

_HK_TO_SNAKE = {  # HK camelCase -> raw.<type> snake_case
    "type": "<type>_type", "sourceName": "source_name",
    "startDate": "start_ts", "endDate": "end_ts", "unit": "unit", "value": "value",
}
_REQUIRED_COLUMNS = {"<type>_type", "source_name", "start_ts"}
_TARGET_COLUMNS = [*_HK_TO_SNAKE.values(), "source_file", "source_sha256"]


@dataclass(frozen=True)
class LoadResult:
    path: Path
    sha256: str
    rows_read: int
    rows_inserted: int
    skipped: bool


def parse_<type>_csv(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="utf-8") as f:
        first_line = f.readline()
    skiprows = 1 if first_line.startswith("sep=") else 0
    df = pd.read_csv(path, skiprows=skiprows).rename(columns=_HK_TO_SNAKE)
    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing required columns: {sorted(missing)}")
    for col in _HK_TO_SNAKE.values():
        if col not in df.columns:  # tolerate missing optionals -> NULL
            df[col] = pd.NA
    df["start_ts"] = pd.to_datetime(df["start_ts"], utc=True)
    df["end_ts"] = pd.to_datetime(df["end_ts"], utc=True)
    return df[list(_HK_TO_SNAKE.values())]


def load_<type>_csv(path: Path, engine: Engine | None = None) -> LoadResult:
    engine = engine or get_engine()
    sha = hash_file(path)
    with engine.connect() as conn:
        if already_loaded(conn, sha):
            return LoadResult(path, sha, 0, 0, skipped=True)
    df = parse_<type>_csv(path).assign(source_file=path.name, source_sha256=sha)
    df = df[_TARGET_COLUMNS]
    with engine.begin() as conn:
        record_file(conn, sha, path.name)
        inserted = upsert_rows(
            conn, df, table="<type>",
            index_elements=["<type>_type", "source_name", "start_ts"],
        )
    logger.info("loaded %s — read %d, inserted %d", path.name, len(df), inserted)
    return LoadResult(path, sha, len(df), inserted, skipped=False)
```

## Step 2 — register in `ingest/loaders/batch.py`

Add `<type>` to the dispatch table so the folder loader
(`uv run python -m ingest.loaders.batch data/raw/`) routes matching files to it.

## Step 3 — raw table DDL (`scripts/init_raw_schema.sql`)

Add `CREATE TABLE IF NOT EXISTS raw.<type> (...)` with the columns the loader
emits **and the composite UNIQUE constraint** that backs ON CONFLICT — without
it the row-level idempotency silently does nothing.

## Step 4 — staging model (`transform/models/staging/stg_<type>.sql`)

This is where **timezone normalization** (UTC → America/Chicago) and the
**source-priority dedup** window function live — never in the loader, never in
intermediate/marts.

## Step 5 — pytest (`tests/test_<type>_loader.py`)

Cover the three idempotency cases:
1. **Fresh load** — rows land, count matches.
2. **Re-load same file** — `rows_inserted == 0`, `skipped is True`.
3. **Partial overlap** — a second file with some new + some seen rows inserts
   only the new ones.

Round-trip through real Postgres for new metric types (the NaN-as-"NaN" bug is
invisible to in-memory tests).

## Verify before you call it done

```bash
uv run ruff check .
uv run pytest tests/test_<type>_loader.py
uv run python -m ingest.loaders.batch data/raw/   # run twice — 2nd run inserts 0
```

Report: files changed, the fresh-load vs re-load row counts (2nd must be 0), and
any OPEN QUESTIONS. Stay in scope — only the five files above.
