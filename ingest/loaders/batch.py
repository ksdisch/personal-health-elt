"""Batch loader: walks a folder of HealthKit CSVs and dispatches each
file to the right sub-loader based on its HK type prefix.

Dispatch table:
    HKQuantityTypeIdentifier* -> ingest.loaders.quantities.load_quantities_csv
    HKCategoryTypeIdentifier* -> [Week 2 TODO]
    Workouts (by filename)    -> [Week 3 TODO]

One failing file never stops the batch — errors are collected and
surfaced in the BatchResult for the caller to decide what to do.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ingest.config import DATABASE_URL
from ingest.loaders.quantities import LoadResult, load_quantities_csv
from ingest.loaders.workouts import load_workouts_csv

logger = logging.getLogger(__name__)

LoaderKind = str  # "quantities" | "categories" | "workouts" | (None when unknown)


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


def load_folder(
    folder: Path,
    *,
    engine: Engine | None = None,
    quantities_loader: Callable[..., LoadResult] = load_quantities_csv,
    workouts_loader: Callable[..., LoadResult] = load_workouts_csv,
) -> BatchResult:
    """Walk folder recursively; load every recognized HK CSV.

    Sub-loaders are injectable for tests — production callers don't pass them.
    """
    if not folder.is_dir():
        raise FileNotFoundError(f"Not a directory: {folder}")

    engine = engine or create_engine(DATABASE_URL)
    result = BatchResult(folder=folder)

    loaders = {"quantities": quantities_loader, "workouts": workouts_loader}

    for path in sorted(folder.rglob("*.csv")):
        kind = dispatch(path)
        loader = loaders.get(kind)
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

    if result.errors:
        print("\nErrors:")
        for path, exc in result.errors:
            print(f"  {path.name}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    _main()
