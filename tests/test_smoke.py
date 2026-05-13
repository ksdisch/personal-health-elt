"""Smoke test — keeps CI green on every Streamlit page from commit #1.

The page-loadability check uses `compile(...)` rather than importing
because Python forbids `import app.pages.05_year_view` (leading-digit
syntax error). `compile` validates syntax + parse-time errors without
executing module bodies — so we don't need a live Postgres connection
to run this in CI.

Page discovery is glob-based (any `app/pages/<digit>*.py`), so adding a
new numbered page is automatically covered — no list to maintain.
"""

from __future__ import annotations

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = REPO_ROOT / "app" / "pages"


def _numbered_pages() -> list[str]:
    """All numbered Streamlit pages in `app/pages/`. Sorted for stable
    pytest IDs."""
    return sorted(p.name for p in PAGES_DIR.glob("*.py") if p.name[0].isdigit())


PAGES = _numbered_pages()


def test_arithmetic_still_works() -> None:
    assert 1 + 1 == 2


def test_pages_directory_is_not_empty() -> None:
    """Guard against the glob silently matching nothing — that would
    turn the parametrized test below into a zero-iteration no-op."""
    assert PAGES, f"No numbered pages found under {PAGES_DIR}"


@pytest.mark.parametrize("filename", PAGES)
def test_page_compiles(filename: str) -> None:
    """Every numbered page parses without raising.

    Catches syntax errors and bad import statements at parse time. Does
    NOT execute module bodies — Streamlit calls at module scope would
    otherwise require a live DB.
    """
    path = PAGES_DIR / filename
    assert path.exists(), f"Expected page at {path}"
    source = path.read_text()
    compile(source, str(path), "exec")
