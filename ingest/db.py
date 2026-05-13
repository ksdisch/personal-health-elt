"""Single source of truth for Postgres connection setup.

Before this module existed, six call sites all wrote
`create_engine(DATABASE_URL)` independently — loaders, the Streamlit
query layer, the test conftest, and the briefing script. Two ways to
configure connection params, two places to debug auth failures, two
places to update when secrets rotate.

Everything that needs a SQLAlchemy `Engine` now imports `get_engine()`
from here. The lone exception is `app/lib/queries.py`, which wraps
`get_engine()` in `@st.cache_resource` so Streamlit's per-rerun reuse
semantics are preserved on top of the same source of truth.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ingest.config import DATABASE_URL


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Process-cached SQLAlchemy Engine for `DATABASE_URL`.

    Cached because `Engine` instances own a connection pool — creating
    a new one per call would defeat pooling. `maxsize=1` because every
    process here ever connects to exactly one database.

    Callers that need to inject a custom engine (e.g. unit tests
    against a separate fixture DB) should pass `engine=...` explicitly
    to the function being tested rather than monkeypatching this
    helper; the loader / queries signatures all accept `engine` as a
    keyword argument with this function's return value as the default.
    """
    return create_engine(DATABASE_URL)
