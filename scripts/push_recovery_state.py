"""Push the latest mart_recovery_state rows to Firestore for Tempo.

One-way data feed: server-writes / client-reads. Writes two documents
under the configured user UID:

    users/{uid}/recovery_state/latest    -- the most recent day's row
    users/{uid}/recovery_state/history   -- {rows: [last 14 days]}

The Tempo PWA (https://github.com/ksdisch/stopwatch) reads these via
SyncFirestore.getDoc and renders a readiness band above its Rhythm
timeline. The schema mirrors mart_recovery_state 1:1 -- treat changes
here as a contract update, same rules as the weekly-health-review skill.

Designed to be invoked from the weekly Prefect flow, but also runnable
standalone:

    uv run python scripts/push_recovery_state.py [--days N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from ingest.db import get_engine  # noqa: E402

_SA_PATH_ENV = "TEMPO_FIREBASE_SA_PATH"
_USER_UID_ENV = "TEMPO_FIREBASE_USER_UID"
_DEFAULT_HISTORY_DAYS = 14

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PushResult:
    """Outcome summary for the weekly flow's structured log."""

    rows_fetched: int
    latest_day: date | None
    skipped: bool
    skip_reason: str | None = None


def _fetch_rows(days: int) -> pd.DataFrame:
    sql = text(
        """
        SELECT day, is_today, recovery_signal,
               rhr_bpm, hrv_ms, hrv_ms_7d_prior_avg,
               zone_2_min_today, zone_2_min_7d, strength_sessions_7d,
               training_load_today, acute_load_7d, chronic_load_28d, acwr,
               days_since_last_workout
        FROM analytics_marts.mart_recovery_state
        WHERE day > current_date - :days
        ORDER BY day
        """
    )
    return pd.read_sql(sql, get_engine(), params={"days": days}, parse_dates=["day"])


def _json_safe(value: Any) -> Any:
    """Coerce a single cell value into something Firestore SDK accepts.

    Pandas/NumPy/SQLAlchemy hand us a mix of:
      - pd.Timestamp / datetime / date  -> ISO 'YYYY-MM-DD' (day grain)
      - numpy.float64 / numpy.int64     -> Python float / int
      - Decimal                         -> float (mart values are bounded)
      - NaN / NaT / None                -> None
      - bool                            -> bool
    Anything we don't recognize falls through unchanged; if Firestore
    rejects it the caller sees a clear traceback rather than a silent
    type swap.
    """
    if value is None:
        return None
    # Catch pandas NaT before bool/float branches (NaT is not Falsy nicely).
    if value is pd.NaT:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # numpy scalars expose .item() to drop to a Python primitive. Avoid
    # importing numpy directly so this module stays light.
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    return value


def serialize_row(row: pd.Series) -> dict[str, Any]:
    """Convert a single mart_recovery_state row to a Firestore-safe dict."""
    return {col: _json_safe(row[col]) for col in row.index}


def build_payloads(df: pd.DataFrame) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return (latest_doc, history_doc). `latest_doc` is None on empty input."""
    if df.empty:
        return None, {"rows": [], "updated_at": datetime.utcnow().isoformat() + "Z"}
    rows = [serialize_row(row) for _, row in df.iterrows()]
    history_doc = {"rows": rows, "updated_at": datetime.utcnow().isoformat() + "Z"}
    latest_doc = dict(rows[-1])
    latest_doc["updated_at"] = history_doc["updated_at"]
    return latest_doc, history_doc


def _missing_env() -> list[str]:
    return [name for name in (_SA_PATH_ENV, _USER_UID_ENV) if not os.environ.get(name)]


def _firestore_client():
    """Lazy import so the standalone serialization tests don't need firebase-admin."""
    import firebase_admin
    from firebase_admin import credentials, firestore

    sa_path = os.environ[_SA_PATH_ENV]
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(sa_path))
    return firestore.client()


def push(*, days: int = _DEFAULT_HISTORY_DAYS, dry_run: bool = False) -> PushResult:
    """Fetch the last `days` rows of mart_recovery_state and push to Firestore.

    No-ops with a structured reason when env vars are unset (so the weekly
    flow can run on machines that haven't enrolled in the feed). Returns a
    PushResult either way -- the caller logs the summary.
    """
    missing = _missing_env()
    if missing and not dry_run:
        _log.info("recovery_state push skipped: missing env vars %s", missing)
        return PushResult(
            rows_fetched=0,
            latest_day=None,
            skipped=True,
            skip_reason=f"missing env: {','.join(missing)}",
        )

    df = _fetch_rows(days=days)
    latest_doc, history_doc = build_payloads(df)
    rows_fetched = len(df)
    latest_day = df["day"].iloc[-1].date() if rows_fetched else None

    if dry_run:
        _log.info(
            "[dry-run] would push %d row(s); latest_day=%s; latest_doc keys=%s",
            rows_fetched,
            latest_day,
            sorted(latest_doc.keys()) if latest_doc else [],
        )
        return PushResult(rows_fetched=rows_fetched, latest_day=latest_day, skipped=False)

    if latest_doc is None:
        _log.warning("recovery_state push: no rows returned; nothing to write")
        return PushResult(
            rows_fetched=0,
            latest_day=None,
            skipped=True,
            skip_reason="empty mart",
        )

    uid = os.environ[_USER_UID_ENV]
    db = _firestore_client()
    base = db.collection("users").document(uid).collection("recovery_state")
    base.document("latest").set(latest_doc)
    base.document("history").set(history_doc)
    _log.info(
        "recovery_state push: wrote latest (%s) + history (%d rows) for uid=%s",
        latest_day,
        rows_fetched,
        uid,
    )
    return PushResult(rows_fetched=rows_fetched, latest_day=latest_day, skipped=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=_DEFAULT_HISTORY_DAYS,
        help=f"History window (default {_DEFAULT_HISTORY_DAYS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + serialize but do not write to Firestore.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log INFO-level progress to stderr.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = push(days=args.days, dry_run=args.dry_run)
    if result.skipped:
        print(f"skipped: {result.skip_reason}")
    else:
        print(f"pushed {result.rows_fetched} row(s); latest_day={result.latest_day}")


if __name__ == "__main__":
    main()
