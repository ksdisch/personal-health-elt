"""Unit tests for parse_categories_csv (pure function, no DB)."""
from pathlib import Path

import pandas as pd
import pytest

from ingest.loaders.categories import parse_categories_csv

_SLEEP_HEADER = (
    "type,sourceName,sourceVersion,productType,device,"
    "startDate,endDate,value,HKTimeZone\n"
)
_SLEEP_ROW = (
    "HKCategoryTypeIdentifierSleepAnalysis,"
    "Kyle's Apple Watch,26.2,Watch7,,"
    "2026-03-21 06:07:07 +0000,2026-03-21 06:20:33 +0000,"
    "asleepCore,America/Phoenix\n"
)

_MINDFUL_HEADER = (
    "type,sourceName,sourceVersion,productType,device,"
    "startDate,endDate,value\n"
)
_MINDFUL_ROW = (
    "HKCategoryTypeIdentifierMindfulSession,"
    "Waking Up,878,iPhone18,,"
    "2026-03-26 14:38:22 +0000,2026-03-26 14:48:58 +0000,"
    "notApplicable\n"
)

_HRE_HEADER = (
    "type,sourceName,sourceVersion,productType,device,"
    "startDate,endDate,value,HKHeartRateEventThreshold\n"
)
_HRE_ROW = (
    "HKCategoryTypeIdentifierHighHeartRateEvent,"
    "Kyle's Apple Watch,26.2,Watch7,,"
    "2026-04-12 02:47:55 +0000,2026-04-12 02:57:55 +0000,"
    "notApplicable,120 count/min\n"
)

_STAND_HEADER = (
    "type,sourceName,sourceVersion,productType,device,"
    "startDate,endDate,value\n"
)
_STAND_ROW = (
    "HKCategoryTypeIdentifierAppleStandHour,"
    "Kyle's Apple Watch,26.2,Watch7,,"
    "2026-03-20 20:00:00 +0000,2026-03-20 20:00:00 +0000,"
    "stood\n"
)


def _write_csv(
    tmp_path: Path,
    *,
    header: str,
    rows: str,
    include_sep_hint: bool,
    name: str = "cat.csv",
) -> Path:
    content = ""
    if include_sep_hint:
        content += "sep=,\n"
    content += header
    content += rows
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_sleep_stage_row(tmp_path: Path) -> None:
    df = parse_categories_csv(
        _write_csv(tmp_path, header=_SLEEP_HEADER, rows=_SLEEP_ROW, include_sep_hint=True)
    )
    assert len(df) == 1
    row = df.iloc[0]
    assert row["category_type"] == "HKCategoryTypeIdentifierSleepAnalysis"
    assert row["category_value"] == "asleepCore"
    assert row["hk_time_zone"] == "America/Phoenix"
    assert row["end_ts"] > row["start_ts"]


def test_parse_mindful_session_row(tmp_path: Path) -> None:
    df = parse_categories_csv(
        _write_csv(tmp_path, header=_MINDFUL_HEADER, rows=_MINDFUL_ROW, include_sep_hint=True)
    )
    assert len(df) == 1
    row = df.iloc[0]
    assert row["category_value"] == "notApplicable"
    duration = (row["end_ts"] - row["start_ts"]).total_seconds()
    assert duration > 0


def test_parse_high_hr_event_preserves_threshold(tmp_path: Path) -> None:
    df = parse_categories_csv(
        _write_csv(tmp_path, header=_HRE_HEADER, rows=_HRE_ROW, include_sep_hint=True)
    )
    assert len(df) == 1
    row = df.iloc[0]
    assert row["category_type"] == "HKCategoryTypeIdentifierHighHeartRateEvent"
    assert row["hk_heart_rate_threshold"] == "120 count/min"


def test_parse_apple_stand_hour_row(tmp_path: Path) -> None:
    df = parse_categories_csv(
        _write_csv(tmp_path, header=_STAND_HEADER, rows=_STAND_ROW, include_sep_hint=True)
    )
    assert len(df) == 1
    row = df.iloc[0]
    assert row["category_type"] == "HKCategoryTypeIdentifierAppleStandHour"
    assert row["category_value"] == "stood"
    # AppleStandHour rows are point-in-time in this export: end_ts == start_ts.
    assert row["start_ts"] == row["end_ts"]


def test_parse_csv_without_optional_columns(tmp_path: Path) -> None:
    """Mindful CSVs have neither HKTimeZone nor HKHeartRateEventThreshold —
    parsing should succeed and land those fields as null."""
    df = parse_categories_csv(
        _write_csv(tmp_path, header=_MINDFUL_HEADER, rows=_MINDFUL_ROW, include_sep_hint=True)
    )
    assert pd.isna(df["hk_time_zone"].iloc[0])
    assert pd.isna(df["hk_heart_rate_threshold"].iloc[0])


def test_parse_raises_when_required_column_missing(tmp_path: Path) -> None:
    """`startDate` is required — without it the loader can't build the natural key."""
    path = tmp_path / "bad.csv"
    path.write_text(
        "type,sourceName,sourceVersion,productType,device,endDate,value\n"
        "HKCategoryTypeIdentifierSleepAnalysis,Watch,1,Watch7,,"
        "2026-03-21 06:20:33 +0000,asleepCore\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required columns"):
        parse_categories_csv(path)


def test_parse_strips_sep_hint(tmp_path: Path) -> None:
    """`sep=,\\n` is an Excel display hint — must be stripped before pandas reads."""
    with_hint = parse_categories_csv(
        _write_csv(
            tmp_path,
            header=_SLEEP_HEADER,
            rows=_SLEEP_ROW,
            include_sep_hint=True,
            name="hint.csv",
        )
    )
    without_hint = parse_categories_csv(
        _write_csv(
            tmp_path,
            header=_SLEEP_HEADER,
            rows=_SLEEP_ROW,
            include_sep_hint=False,
            name="nohint.csv",
        )
    )
    assert len(with_hint) == 1
    assert len(without_hint) == 1


def test_parse_header_only_returns_empty_dataframe(tmp_path: Path) -> None:
    """Header-only CSVs are common for categories the user has never recorded."""
    df = parse_categories_csv(
        _write_csv(tmp_path, header=_SLEEP_HEADER, rows="", include_sep_hint=True)
    )
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
