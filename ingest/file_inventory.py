"""Hash-based inventory of incoming CSV exports.

Apple re-exports contain full history on every dump, so loaders MUST be
idempotent. The inventory tracks the SHA256 of each loaded file; a file whose
hash is already in the inventory is skipped.

This module is pure Python — no database dependency. Persistence lives
elsewhere (raw.file_inventory table), and callers pass the set of known
hashes in. Keeping it pure makes it trivially unit-testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

_READ_CHUNK_BYTES = 1 << 20  # 1 MiB


def hash_file(path: Path) -> str:
    """Return SHA256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_READ_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class FileEntry:
    """A candidate file plus its content hash."""

    path: Path
    sha256: str


def scan(drop_dir: Path) -> list[FileEntry]:
    """Hash every .csv in drop_dir. Returns entries sorted by path for determinism.

    Missing or empty directories return an empty list rather than raising —
    Prefect will call this on every run, and an empty drop folder is normal.
    """
    if not drop_dir.is_dir():
        return []
    return [FileEntry(path=p, sha256=hash_file(p)) for p in sorted(drop_dir.glob("*.csv"))]


def unseen(entries: list[FileEntry], seen_hashes: set[str]) -> list[FileEntry]:
    """Filter to entries whose hash is not in seen_hashes."""
    return [e for e in entries if e.sha256 not in seen_hashes]
