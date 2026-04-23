"""Loader for Apple Health workout sessions.

Workouts have a start and end timestamp, an activity type, and summary totals
(duration, distance, active energy). They form the outer boundary for
range-based joins against HR samples in the intermediate layer.
"""
from __future__ import annotations

from pathlib import Path


def load_workouts_csv(path: Path) -> int:
    """Parse a Health Auto Export workouts CSV and write to raw.workouts."""
    raise NotImplementedError("Week 3 — implement workouts loader")
