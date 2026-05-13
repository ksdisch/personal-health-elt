"""Batch loader: walks a folder of HealthKit CSVs and dispatches each
file to the right sub-loader based on its HK type prefix.

Dispatch table:
    HKQuantityTypeIdentifier* -> ingest.loaders.quantities.load_quantities_csv
    HKCategoryTypeIdentifier* -> ingest.loaders.categories.load_categories_csv
    HKWorkoutActivityType*    -> ingest.loaders.workouts.load_workouts_csv

One failing file never stops the batch — errors are collected and
surfaced in the BatchResult for the caller to decide what to do.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from ingest.db import get_engine
from ingest.loaders.categories import load_categories_csv
from ingest.loaders.quantities import LoadResult, load_quantities_csv
from ingest.loaders.workouts import load_workouts_csv

logger = logging.getLogger(__name__)

LoaderKind = str  # "quantities" | "categories" | "workouts" | (None when unknown)

_HK_PREFIXES = (
    "HKQuantityTypeIdentifier",
    "HKCategoryTypeIdentifier",
    "HKWorkoutActivityType",
)


def dispatch(path: Path) -> LoaderKind | None:
    """Return the loader kind for a file, or None if we don't handle it yet."""
    name = path.name
    if "HKQuantityTypeIdentifier" in name:
        return "quantities"
    if "HKWorkoutActivityType" in name:
        return "workouts"
    if "HKCategoryTypeIdentifier" in name:
        return "categories"
    return None


def metric_type_from_path(path: Path) -> str:
    """Strip the HK prefix from a filename's stem to get the metric name.

    `HKQuantityTypeIdentifierRestingHeartRate.csv` → `RestingHeartRate`.
    Returns `"unknown"` when no known prefix matches. Used to label
    per-metric-type lines in the batch summary so an operator can
    immediately spot which family was affected.
    """
    stem = path.stem
    for prefix in _HK_PREFIXES:
        if stem.startswith(prefix):
            return stem.removeprefix(prefix)
    return "unknown"


@dataclass
class BatchResult:
    folder: Path
    loaded: list[LoadResult] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, Exception]] = field(default_factory=list)

    @property
    def files_loaded(self) -> int:
        return sum(1 for r in self.loaded if not r.skipped)

    @property
    def files_already_loaded(self) -> int:
        return sum(1 for r in self.loaded if r.skipped)

    @property
    def total_rows_inserted(self) -> int:
        return sum(r.rows_inserted for r in self.loaded)

    def per_kind_summary(self) -> dict[str, dict[str, int]]:
        """Aggregate counts per loader kind (quantities / categories / workouts).

        Each value dict has `files_loaded`, `files_already_loaded`,
        `rows_inserted`, and `files_errored`. Kinds with zero activity
        are omitted so the summary stays tight.
        """
        out: dict[str, dict[str, int]] = {}
        for r in self.loaded:
            kind = dispatch(r.path) or "unknown"
            d = out.setdefault(
                kind,
                {
                    "files_loaded": 0,
                    "files_already_loaded": 0,
                    "rows_inserted": 0,
                    "files_errored": 0,
                },
            )
            if r.skipped:
                d["files_already_loaded"] += 1
            else:
                d["files_loaded"] += 1
            d["rows_inserted"] += r.rows_inserted
        for path, _exc in self.errors:
            kind = dispatch(path) or "unknown"
            d = out.setdefault(
                kind,
                {
                    "files_loaded": 0,
                    "files_already_loaded": 0,
                    "rows_inserted": 0,
                    "files_errored": 0,
                },
            )
            d["files_errored"] += 1
        return out

    def per_metric_type_summary(self) -> list[dict[str, object]]:
        """One row per successfully-processed file (loaded or already-seen),
        labelled with its metric_type. Sorted by filename for stable logs.
        """
        return [
            {
                "metric_type": metric_type_from_path(r.path),
                "kind": dispatch(r.path) or "unknown",
                "rows_read": r.rows_read,
                "rows_inserted": r.rows_inserted,
                "skipped": r.skipped,
            }
            for r in sorted(self.loaded, key=lambda r: r.path.name)
        ]

    def errored_metric_types(self) -> list[dict[str, str]]:
        """One row per error — metric_type, path, error type, truncated message.

        Operators use this list to jump straight to the bad file on a
        partial failure. Error messages are truncated to 200 chars so a
        runaway stack trace can't drown the structured log.
        """
        return [
            {
                "metric_type": metric_type_from_path(path),
                "kind": dispatch(path) or "unknown",
                "path": str(path),
                "error_type": type(exc).__name__,
                "error_msg": str(exc)[:200],
            }
            for path, exc in self.errors
        ]

    def format_summary_table(self) -> str:
        """Multi-line human-readable summary suitable for one log message."""
        per_kind = self.per_kind_summary()
        if not per_kind:
            return "batch summary: no files processed"

        header = f"{'kind':<12}  {'loaded':>6}  {'already':>7}  {'rows':>10}  {'errored':>7}"
        rows = [header, "-" * len(header)]
        for kind in ("quantities", "categories", "workouts", "unknown"):
            if kind not in per_kind:
                continue
            d = per_kind[kind]
            rows.append(
                f"{kind:<12}  {d['files_loaded']:>6}  "
                f"{d['files_already_loaded']:>7}  "
                f"{d['rows_inserted']:>10}  "
                f"{d['files_errored']:>7}"
            )
        return "\n".join(rows)


def load_folder(
    folder: Path,
    *,
    engine: Engine | None = None,
    quantities_loader: Callable[..., Any] = load_quantities_csv,
    workouts_loader: Callable[..., Any] = load_workouts_csv,
    categories_loader: Callable[..., Any] = load_categories_csv,
) -> BatchResult:
    """Walk folder recursively; load every recognized HK CSV.

    Sub-loaders are injectable for tests — production callers don't pass them.
    """
    if not folder.is_dir():
        raise FileNotFoundError(f"Not a directory: {folder}")

    engine = engine or get_engine()
    result = BatchResult(folder=folder)

    loaders = {
        "quantities": quantities_loader,
        "workouts": workouts_loader,
        "categories": categories_loader,
    }

    for path in sorted(folder.rglob("*.csv")):
        kind = dispatch(path)
        loader = loaders.get(kind) if kind is not None else None
        if loader is not None:
            try:
                result.loaded.append(loader(path, engine=engine))
            except Exception as exc:
                logger.error("FAILED %s: %s", path.name, exc)
                result.errors.append((path, exc))
        else:
            logger.info("skip %s (no loader yet for kind=%s)", path.name, kind)
            result.skipped.append(path)

    return result


def _main() -> None:
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m ingest.loaders.batch <folder>")
        sys.exit(2)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = load_folder(Path(sys.argv[1]))

    print("\n─── batch summary ───")
    print(f"folder:             {result.folder}")
    print(f"files loaded:       {result.files_loaded}")
    print(f"files already seen: {result.files_already_loaded}")
    print(f"files skipped:      {len(result.skipped)}")
    print(f"files errored:      {len(result.errors)}")
    print(f"new rows inserted:  {result.total_rows_inserted}")
    print()
    print(result.format_summary_table())

    if result.errors:
        print("\nErrors:")
        for entry in result.errored_metric_types():
            print(
                f"  [{entry['kind']}] {entry['metric_type']}: "
                f"{entry['error_type']}: {entry['error_msg']}"
            )


if __name__ == "__main__":
    _main()
