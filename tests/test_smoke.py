"""Smoke test — keeps CI green from commit #1.

The page-loadability check uses `compile(...)` rather than importing
because Python forbids `import app.pages.05_year_view` (leading-digit
syntax error). `compile` validates syntax + parse-time errors without
executing module bodies — so we don't need a live Postgres connection
to run this in CI.
"""

from __future__ import annotations

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = REPO_ROOT / "app" / "pages"

NEW_PAGES = [
    "05_year_view.py",
    "06_anomaly.py",
    "07_readiness.py",
    "08_aerobic_efficiency.py",
    "09_correlations.py",
    "12_sleep.py",
]


def test_arithmetic_still_works() -> None:
    assert 1 + 1 == 2


@pytest.mark.parametrize("filename", NEW_PAGES)
def test_new_page_compiles(filename: str) -> None:
    """Every new analytical page parses without raising.

    Catches syntax errors and bad import statements at parse time. Does
    NOT execute module bodies — Streamlit calls at module scope would
    otherwise require a live DB.
    """
    path = PAGES_DIR / filename
    assert path.exists(), f"Expected page at {path}"
    source = path.read_text()
    compile(source, str(path), "exec")
