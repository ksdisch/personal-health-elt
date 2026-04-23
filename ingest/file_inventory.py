"""Hash-based inventory of incoming CSV exports.

Apple re-exports contain full history on every dump, so loaders MUST be
idempotent. The inventory tracks the SHA256 of each loaded file; a file whose
hash is already in the inventory is skipped.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def hash_file(path: Path) -> str:
    """Return SHA256 of a file's bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_new_files(drop_dir: Path, seen_hashes: set[str]) -> list[Path]:
    """Return CSVs in drop_dir whose hash is not in seen_hashes."""
    raise NotImplementedError("Week 1 — back this with raw.file_inventory")
