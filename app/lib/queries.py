"""Shared SQL helpers for Streamlit pages.

Any query that touches raw HR samples will scan millions of rows — those
functions MUST be wrapped in @st.cache_data at the function boundary. Apply
the decorator here, not inside page files.
"""
from __future__ import annotations

# Query helpers will land here as marts come online (Week 1+).
