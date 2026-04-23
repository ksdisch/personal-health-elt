"""Loader for Apple Health category metrics.

Covers sleep stages, mindfulness sessions, symptoms, and other categorical
events. Lands rows in raw.categories.
"""
from __future__ import annotations

from pathlib import Path


def load_categories_csv(path: Path) -> int:
    """Parse a Health Auto Export categories CSV and write to raw.categories."""
    raise NotImplementedError("Week 2 — implement categories loader")
