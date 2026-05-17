"""Generate today's workout coach recommendation card.

Queries `analytics_marts.mart_recovery_state` for the latest available
day and `analytics_marts.mart_training_load` for the trailing 14 days,
then emits a Markdown H2 block to stdout describing today's recommended
session (type, target zone, duration) with the actual recovery numbers
that drove the call.

The `daily-workout-coach` skill (at `~/Cowork/skills/daily-workout-coach/`)
captures this output and writes it into the vault at
`40-areas/health/daily-workout-coach.md` — one H2 per day, newest on top
— mirroring the `weekly-health-review` skill's vault pattern.

The recommendation policy is a small Python decision table keyed on
`recovery_signal` × `acwr` × `days_since_last_workout` × Zone-2 deficit ×
strength deficit. It reflects the user's stated training philosophy from
weekly_health_review.py: 3x60min Zone 2 + 2 strength per week, ACWR
sweet spot 0.8–1.3, >1.5 = red zone, <0.8 = safe to add volume.

Standalone:

    uv run python scripts/daily_workout_coach.py [--days N]

The script always reports on the latest available day in
`mart_recovery_state`, not literally `current_date`, so it renders
plausible output in dev environments where the warehouse trails real
time.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
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

_ZONE_2_WEEKLY_TARGET_MIN = 180  # matches weekly-workout-planner / weekly review
_STRENGTH_WEEKLY_TARGET = 2  # sessions per week


@dataclass(frozen=True)
class Recommendation:
    """The output of the recommendation policy.

    Structured rather than a free-form string so the markdown renderer
    (and any future automated consumer) can format the same data multiple
    ways without re-parsing English.
    """

    session_type: str  # e.g. "Zone 2 base", "Strength", "Rest", "High-intensity OK"
    target_zone: str | None  # e.g. "Z2", "Z3-Z4", "Z1", or None for rest
    target_min: int  # 0 for rest
    headline: str  # one-sentence summary used as the card subhead
    rationale: list[str]  # bullet list of "why" lines, referencing real numbers


def _fetch_recovery(days: int) -> pd.DataFrame:
    """Trailing-`days` slice from `mart_recovery_state`."""
    sql = text(
        """
        SELECT day, recovery_signal, rhr_bpm, hrv_ms, hrv_ms_7d_prior_avg,
               zone_2_min_today, zone_2_min_7d, strength_sessions_7d,
               training_load_today, acute_load_7d, chronic_load_28d, acwr,
               days_since_last_workout
        FROM analytics_marts.mart_recovery_state
        WHERE day > (
                SELECT max(day) FROM analytics_marts.mart_recovery_state
              ) - :days
        ORDER BY day
        """
    )
    return pd.read_sql(sql, get_engine(), params={"days": days}, parse_dates=["day"])


def _fetch_training_load(days: int) -> pd.DataFrame:
    """Trailing-`days` slice from `mart_training_load`."""
    sql = text(
        """
        SELECT day, zone_2_min, training_load, acute_load_7d,
               chronic_load_28d, acwr, strength_sessions_7d, strength_min_7d
        FROM analytics_marts.mart_training_load
        WHERE day > (
                SELECT max(day) FROM analytics_marts.mart_training_load
              ) - :days
        ORDER BY day
        """
    )
    return pd.read_sql(sql, get_engine(), params={"days": days}, parse_dates=["day"])


def _fmt(value: object, spec: str = ".1f", default: str = "—") -> str:
    if value is None or pd.isna(value):
        return default
    return f"{value:{spec}}"


def recommend(
    latest: pd.Series,
    training_load_14d: pd.DataFrame,
) -> Recommendation:
    """Map (latest recovery row, trailing training-load history) → today's session.

    Policy is intentionally a small set of explicit branches rather than
    a tunable model — the user is one person and the rules are easy to
    reason about. Order matters: red flags first, then volume guards,
    then opportunities.
    """

    signal = latest["recovery_signal"]
    acwr = latest["acwr"]
    days_since = latest["days_since_last_workout"]
    z2_7d = latest["zone_2_min_7d"]
    strength_7d = (
        int(latest["strength_sessions_7d"]) if pd.notna(latest["strength_sessions_7d"]) else 0
    )

    z2_pct = (z2_7d / _ZONE_2_WEEKLY_TARGET_MIN * 100) if pd.notna(z2_7d) else None
    z2_pct_str = f"{z2_pct:.0f}%" if z2_pct is not None else "unknown"

    # --- Red-flag branches first: never overrule a strained signal.
    if signal == "strained":
        rationale = [
            f"Recovery signal is **strained** ({_SIGNAL_EMOJI['strained']}).",
            (
                f"ACWR {_fmt(acwr, '.2f')} "
                + ("(injury-risk zone, >1.5)." if pd.notna(acwr) and acwr > 1.5 else ".")
            ),
        ]
        if pd.notna(latest["hrv_ms"]) and pd.notna(latest["hrv_ms_7d_prior_avg"]):
            hrv_drop_pct = (
                (latest["hrv_ms_7d_prior_avg"] - latest["hrv_ms"])
                / latest["hrv_ms_7d_prior_avg"]
                * 100
            )
            if hrv_drop_pct >= 15:
                rationale.append(
                    f"HRV {_fmt(latest['hrv_ms'], '.1f')} ms is "
                    f"{hrv_drop_pct:.0f}% below its 7-day prior avg "
                    f"({_fmt(latest['hrv_ms_7d_prior_avg'], '.1f')} ms)."
                )
        # ACWR spike → full rest; otherwise easy walk is fine and helps recovery.
        if pd.notna(acwr) and acwr > 1.5:
            return Recommendation(
                session_type="Rest day",
                target_zone=None,
                target_min=0,
                headline="Take a rest day. Body is in injury-risk territory.",
                rationale=rationale,
            )
        return Recommendation(
            session_type="Easy walk (Zone 1)",
            target_zone="Z1",
            target_min=30,
            headline="Active recovery only — light Zone 1 walk, no Z2 or strength.",
            rationale=rationale
            + [
                "Light movement aids recovery without adding load.",
            ],
        )

    if signal == "insufficient_data":
        return Recommendation(
            session_type="Conservative Zone 2",
            target_zone="Z2",
            target_min=30,
            headline="Not enough recent data to call it — default to a short Zone 2.",
            rationale=[
                "Recovery signal is `insufficient_data` (missing HRV, ACWR, or both).",
                "30 min Z2 is a safe default that doesn't accumulate load.",
            ],
        )

    # --- Neutral: default to recovery if just worked out, otherwise standard Z2.
    if signal == "neutral":
        if pd.notna(days_since) and days_since == 0:
            return Recommendation(
                session_type="Easy recovery",
                target_zone="Z1",
                target_min=20,
                headline="You already trained today — short walk or skip.",
                rationale=[
                    f"Recovery signal is **neutral** ({_SIGNAL_EMOJI['neutral']}).",
                    "`days_since_last_workout` = 0 means today's session is already in.",
                ],
            )
        return Recommendation(
            session_type="Zone 2",
            target_zone="Z2",
            target_min=45,
            headline="Standard Zone 2 session — neutral recovery, steady volume.",
            rationale=[
                f"Recovery signal is **neutral** ({_SIGNAL_EMOJI['neutral']}).",
                f"Zone 2 progress: {_fmt(z2_7d, '.0f')} / "
                f"{_ZONE_2_WEEKLY_TARGET_MIN} min ({z2_pct_str}) over last 7d.",
            ],
        )

    # --- Well-recovered: opportunity branches.
    # well_recovered + volume already too high → defensive Z2 only.
    if pd.notna(acwr) and acwr > 1.5:
        return Recommendation(
            session_type="Zone 2 (defensive)",
            target_zone="Z2",
            target_min=30,
            headline="Recovery is fine but volume is already in the red — Z2 only, short.",
            rationale=[
                f"Recovery signal is **well_recovered** ({_SIGNAL_EMOJI['well_recovered']}).",
                f"ACWR {_fmt(acwr, '.2f')} is >1.5 (injury-risk zone).",
                "Don't add stress on top of a high acute load even when HRV looks good.",
            ],
        )

    if pd.notna(acwr) and acwr > 1.3:
        return Recommendation(
            session_type="Zone 2",
            target_zone="Z2",
            target_min=45,
            headline="Hold steady at Zone 2 — ACWR is climbing.",
            rationale=[
                f"Recovery signal is **well_recovered** ({_SIGNAL_EMOJI['well_recovered']}).",
                f"ACWR {_fmt(acwr, '.2f')} is above 1.3; cap intensity until it settles.",
            ],
        )

    # well_recovered + ACWR < 0.8 (under-training) → safe to add volume.
    if pd.notna(acwr) and acwr < 0.8:
        return Recommendation(
            session_type="Zone 2 (build)",
            target_zone="Z2",
            target_min=75,
            headline="Under-trained and well-recovered — add volume with a longer Z2.",
            rationale=[
                f"Recovery signal is **well_recovered** ({_SIGNAL_EMOJI['well_recovered']}).",
                f"ACWR {_fmt(acwr, '.2f')} is below 0.8 — the warehouse says you can absorb more.",
                f"Zone 2 progress: {_fmt(z2_7d, '.0f')} / "
                f"{_ZONE_2_WEEKLY_TARGET_MIN} min ({z2_pct_str}); long Z2 closes the gap.",
            ],
        )

    # well_recovered + ACWR sweet spot (0.8–1.3). Pick by deficit.
    needs_strength = strength_7d < _STRENGTH_WEEKLY_TARGET
    z2_deficit = z2_pct is None or z2_pct < 70

    if needs_strength and not z2_deficit:
        return Recommendation(
            session_type="Strength session",
            target_zone=None,
            target_min=45,
            headline="Zone 2 weekly target is on track — hit strength today.",
            rationale=[
                f"Recovery signal is **well_recovered** ({_SIGNAL_EMOJI['well_recovered']}).",
                f"Strength sessions in last 7d: **{strength_7d}** "
                f"(target {_STRENGTH_WEEKLY_TARGET}).",
                f"Zone 2 progress: {z2_pct_str} of weekly target — no Z2 deficit.",
            ],
        )

    if z2_deficit:
        return Recommendation(
            session_type="Zone 2 base",
            target_zone="Z2",
            target_min=60,
            headline="Hit a full 60-min Zone 2 to chase the weekly target.",
            rationale=[
                f"Recovery signal is **well_recovered** ({_SIGNAL_EMOJI['well_recovered']}).",
                f"Zone 2 progress: {_fmt(z2_7d, '.0f')} / "
                f"{_ZONE_2_WEEKLY_TARGET_MIN} min ({z2_pct_str}) over last 7d.",
                f"ACWR {_fmt(acwr, '.2f')} is in the sweet spot — safe to push duration.",
            ],
        )

    # well_recovered + Z2 target met + strength on track → green light for intensity.
    return Recommendation(
        session_type="High-intensity OK (intervals or tempo)",
        target_zone="Z3-Z4",
        target_min=45,
        headline="Green light on intensity — base targets met and recovery is solid.",
        rationale=[
            f"Recovery signal is **well_recovered** ({_SIGNAL_EMOJI['well_recovered']}).",
            f"ACWR {_fmt(acwr, '.2f')} is in the sweet spot (0.8–1.3).",
            f"Weekly base is met: Z2 {z2_pct_str}, strength {strength_7d}/"
            f"{_STRENGTH_WEEKLY_TARGET}.",
        ],
    )


def render_card(
    recovery: pd.DataFrame,
    training_load_14d: pd.DataFrame,
    *,
    today: date | None = None,
) -> str:
    """Render the daily H2 markdown card.

    `today` is mostly for testability — production calls leave it None
    and the card uses the latest day available in the warehouse.
    """

    if recovery.empty:
        label_date = today or date.today()
        return (
            f"## {label_date} ({label_date.strftime('%a')})\n\n"
            "_No recovery data available. Run the ingest pipeline + `dbt build`._\n"
        )

    latest = recovery.iloc[-1]
    day_local = latest["day"].date()
    day_label = f"## {day_local} ({day_local.strftime('%a')})"

    rec = recommend(latest, training_load_14d)

    target_line = (
        f"**{rec.target_min} min** in **{rec.target_zone}**"
        if rec.target_zone is not None
        else "**Rest** (no session)"
    )

    rationale_md = "\n".join(f"- {line}" for line in rec.rationale)

    sig_emoji = _SIGNAL_EMOJI.get(latest["recovery_signal"], "")
    sig_label = _SIGNAL_LABEL.get(latest["recovery_signal"], latest["recovery_signal"])

    strength_count = (
        int(latest["strength_sessions_7d"]) if pd.notna(latest["strength_sessions_7d"]) else 0
    )
    days_since_display = (
        str(int(latest["days_since_last_workout"]))
        if pd.notna(latest["days_since_last_workout"])
        else "—"
    )

    # Snapshot of inputs that drove the call. Mirrors weekly review's snapshot.
    snapshot_lines = [
        f"- Recovery signal: {sig_emoji} **{sig_label}**",
        f"- RHR: **{_fmt(latest['rhr_bpm'], '.0f')} bpm** "
        f"(HRV: **{_fmt(latest['hrv_ms'], '.1f')} ms**, "
        f"prior 7d avg {_fmt(latest['hrv_ms_7d_prior_avg'], '.1f')} ms)",
        f"- ACWR: **{_fmt(latest['acwr'], '.2f')}** "
        f"(acute {_fmt(latest['acute_load_7d'], '.1f')}, "
        f"chronic {_fmt(latest['chronic_load_28d'], '.1f')})",
        f"- Zone 2 last 7d: **{_fmt(latest['zone_2_min_7d'], '.0f')}** / "
        f"{_ZONE_2_WEEKLY_TARGET_MIN} min",
        f"- Strength last 7d: **{strength_count}** / {_STRENGTH_WEEKLY_TARGET} sessions",
        f"- Days since last workout: **{days_since_display}**",
    ]
    snapshot = "\n".join(snapshot_lines)

    # 14d training-load mini-table — only show meaningful workout days. The
    # threshold is "< 1" rather than "== 0" because tiny micro-workouts can
    # register a fractional TRIMP that rounds to "0" in the display but
    # wouldn't otherwise be filtered out.
    tl_rows: list[str] = []
    if not training_load_14d.empty:
        for _, row in training_load_14d.iterrows():
            load = row["training_load"] if pd.notna(row["training_load"]) else 0
            z2 = row["zone_2_min"] if pd.notna(row["zone_2_min"]) else 0
            if load < 1 and z2 < 1:
                continue
            tl_rows.append(
                f"| {row['day'].strftime('%a %m-%d')} "
                f"| {_fmt(load, '.0f')} "
                f"| {_fmt(z2, '.0f')} "
                f"| {_fmt(row['acwr'], '.2f')} |"
            )

    if tl_rows:
        load_section = (
            "\n**Training load — last 14 days (workout days only):**\n\n"
            "| Day | Load (TRIMP) | Z2 (min) | ACWR |\n"
            "|---|---|---|---|\n" + "\n".join(tl_rows) + "\n"
        )
    else:
        load_section = "\n_No workouts logged in the last 14 days._\n"

    md = f"""{day_label}

**Today's call:** {rec.headline}

🎯 **Session:** {rec.session_type} — {target_line}

**Recovery snapshot:**
{snapshot}

**Why:**
{rationale_md}
{load_section}
_Generated from `analytics_marts.mart_recovery_state` + `mart_training_load`._
"""
    return md


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="History window for training-load context (default 14)",
    )
    args = parser.parse_args()

    recovery = _fetch_recovery(days=args.days)
    training_load = _fetch_training_load(days=args.days)
    print(render_card(recovery, training_load))


if __name__ == "__main__":
    main()
