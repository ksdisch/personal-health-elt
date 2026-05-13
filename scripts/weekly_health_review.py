"""Generate the weekly health review briefing.

Queries `analytics_marts.mart_recovery_state` for the last 14 days and
emits a Markdown block (one H2 for the current ISO week) to stdout. The
`weekly-health-review` skill captures this output and writes it into the
vault at `40-areas/health/weekly-health-reviews.md`.

Designed to be invoked from the skill, but also runnable standalone:

    uv run python scripts/weekly_health_review.py [--days N]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

# Allow standalone invocation from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from ingest.db import get_engine  # noqa: E402

_SIGNAL_EMOJI = {
    "well_recovered": "🟢",
    "neutral": "🟡",
    "strained": "🔴",
    "insufficient_data": "⚪",
}

_SIGNAL_LABEL = {
    "well_recovered": "well-recovered",
    "neutral": "neutral",
    "strained": "strained",
    "insufficient_data": "insufficient data",
}

_ZONE_2_WEEKLY_TARGET_MIN = 180  # matches weekly-workout-planner


def _fetch(days: int) -> pd.DataFrame:
    sql = text(
        """
        SELECT day, recovery_signal, rhr_bpm, hrv_ms, hrv_ms_7d_prior_avg,
               zone_2_min_today, zone_2_min_7d, strength_sessions_7d,
               training_load_today, acute_load_7d, chronic_load_28d, acwr,
               days_since_last_workout
        FROM analytics_marts.mart_recovery_state
        WHERE day > current_date - :days
        ORDER BY day
        """
    )
    return pd.read_sql(sql, get_engine(), params={"days": days}, parse_dates=["day"])


def _iso_week_label(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _fmt_or(value, spec: str = ".1f", default: str = "—") -> str:
    if value is None or pd.isna(value):
        return default
    return f"{value:{spec}}"


def _trend_arrow(
    current: float | None,
    baseline: float | None,
    *,
    lower_is_better: bool = False,
) -> str:
    """Up arrow when current is meaningfully above baseline; down for below."""
    if current is None or baseline is None or pd.isna(current) or pd.isna(baseline):
        return ""
    diff = current - baseline
    pct = abs(diff) / baseline if baseline else 0
    if pct < 0.03:
        return "→"
    going_up = diff > 0
    good = (going_up and not lower_is_better) or (not going_up and lower_is_better)
    return ("↑" if going_up else "↓") + (" 🟢" if good else " 🔴")


def render_briefing(df: pd.DataFrame, *, today: date | None = None) -> str:
    today = today or date.today()
    monday = _monday_of(today)
    label = _iso_week_label(today)

    if df.empty:
        return (
            f"## {label} (Week of {monday})\n\n_No recovery data available for the last 14 days._\n"
        )

    last7 = df.tail(7)
    prior7 = df.iloc[-14:-7] if len(df) >= 14 else df.iloc[0:0]
    latest = df.iloc[-1]

    avg_rhr = last7["rhr_bpm"].mean()
    avg_hrv = last7["hrv_ms"].mean()
    z2_7d = latest["zone_2_min_7d"]
    z2_pct = (z2_7d / _ZONE_2_WEEKLY_TARGET_MIN * 100) if pd.notna(z2_7d) else None
    z2_alert = " ⚠️" if z2_pct is not None and z2_pct < 60 else ""
    acwr = latest["acwr"]
    strength_7d = (
        int(latest["strength_sessions_7d"]) if pd.notna(latest["strength_sessions_7d"]) else 0
    )

    signal_counts = Counter(last7["recovery_signal"].dropna())

    rhr_trend = (
        _trend_arrow(avg_rhr, prior7["rhr_bpm"].mean(), lower_is_better=True)
        if not prior7.empty
        else ""
    )
    hrv_trend = _trend_arrow(avg_hrv, prior7["hrv_ms"].mean()) if not prior7.empty else ""

    headline_signal = signal_counts.most_common(1)[0][0] if signal_counts else "insufficient_data"
    headline = f"{_SIGNAL_EMOJI[headline_signal]} {_SIGNAL_LABEL[headline_signal].title()}"
    sig_summary = " · ".join(
        f"{_SIGNAL_EMOJI[k]} {v}" for k, v in sorted(signal_counts.items(), key=lambda kv: -kv[1])
    )

    rec_lines = _recommendations(latest, z2_pct, signal_counts, avg_hrv, prior7)

    table_rows = []
    for _, row in last7.iterrows():
        emoji = _SIGNAL_EMOJI.get(row["recovery_signal"], "")
        table_rows.append(
            f"| {row['day'].strftime('%a %m-%d')} "
            f"| {emoji} "
            f"| {_fmt_or(row['rhr_bpm'], '.0f')} "
            f"| {_fmt_or(row['hrv_ms'], '.1f')} "
            f"| {_fmt_or(row['zone_2_min_today'], '.0f')} "
            f"| {_fmt_or(row['acwr'], '.2f')} |"
        )

    md = f"""## {label} (Week of {monday})

**Signal:** {headline} ({sig_summary})

**Recovery snapshot — last 7 days:**
- RHR: avg **{_fmt_or(avg_rhr, ".0f")} bpm** {rhr_trend}
- HRV (SDNN): avg **{_fmt_or(avg_hrv, ".1f")} ms** {hrv_trend}
- Zone 2 minutes (rolling 7d): **{_fmt_or(z2_7d, ".0f")} / {_ZONE_2_WEEKLY_TARGET_MIN} min** \
({_fmt_or(z2_pct, ".0f")}%){z2_alert}
- Strength sessions (last 7d): **{strength_7d}**
- ACWR (acute:chronic): **{_fmt_or(acwr, ".2f")}**

**Day-by-day:**

| Day | Signal | RHR | HRV | Z2 (min) | ACWR |
|---|---|---|---|---|---|
{chr(10).join(table_rows)}

**Recommendations for next week:**
{chr(10).join(f"- {r}" for r in rec_lines)}

_Generated from `analytics_marts.mart_recovery_state` ({len(df)} days available)._
"""
    return md


def _recommendations(
    latest: pd.Series,
    z2_pct: float | None,
    signal_counts: Counter,
    avg_hrv: float | None,
    prior7: pd.DataFrame,
) -> list[str]:
    """Three to four concrete prescriptions the workout-planner can act on."""
    recs: list[str] = []
    acwr = latest["acwr"]

    # ACWR-driven volume guidance.
    if pd.notna(acwr):
        if acwr > 1.5:
            recs.append(
                f"ACWR is {acwr:.2f} (>1.5, injury-risk zone). **Reduce load** — "
                "swap a Zone 2 session for an easy walk, skip one strength session."
            )
        elif acwr < 0.8:
            recs.append(
                f"ACWR is {acwr:.2f} (<0.8, under-training). **Safe to add volume** "
                "— hit all three Zone 2 sessions and consider a fourth on Saturday."
            )
        else:
            recs.append(
                f"ACWR is {acwr:.2f} (sweet spot 0.8–1.3). **Hold steady** — "
                "keep the standard 3 × 60 min Zone 2 + 2 strength rotation."
            )

    # Zone 2 progress.
    if z2_pct is not None:
        if z2_pct < 60:
            recs.append(
                f"Zone 2 is at **{z2_pct:.0f}%** of target. Prioritize Zone 2 cardio "
                "early in the week (Tue or Wed) before strength sessions accumulate fatigue."
            )
        elif z2_pct >= 100:
            recs.append("Zone 2 target met — consider one bonus session Saturday for build.")

    # HRV trend signal.
    if not prior7.empty and avg_hrv is not None and pd.notna(avg_hrv):
        prior_avg = prior7["hrv_ms"].mean()
        if pd.notna(prior_avg) and avg_hrv < prior_avg * 0.9:
            recs.append(
                "HRV is **trending down vs. prior week**. Frontload recovery: easy "
                "Monday yoga, no stacking strength + cardio same day."
            )

    # Signal distribution.
    strained_days = signal_counts.get("strained", 0)
    if strained_days >= 3:
        recs.append(
            f"**{strained_days} strained days** in the last 7. Lean into Monday yoga and "
            "consider a deload microcycle next week."
        )

    if not recs:
        recs.append("No flags. Run the standard weekly plan.")

    return recs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14, help="History window (default 14)")
    args = parser.parse_args()

    df = _fetch(days=args.days)
    print(render_briefing(df))


if __name__ == "__main__":
    main()
