"""Loader for Apple Health quantity metrics.

Covers heart rate, HRV, weight, sleep duration, VO2 max, resting HR, active
and basal energy, steps, distance — anything expressed as a numeric value
with a timestamp. Lands rows in raw.quantities. Idempotent via upsert on
(metric_name, source, start_ts).
"""
from __future__ import annotations

from pathlib import Path


def load_quantities_csv(path: Path) -> int:
    """Parse a Health Auto Export quantities CSV and write to raw.quantities."""
    raise NotImplementedError("Week 2 — implement generic quantities loader")
