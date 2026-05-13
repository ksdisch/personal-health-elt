"""Unit tests for the batch loader — DB-free via loader injection."""

from pathlib import Path

import pytest

from ingest.loaders.batch import dispatch, load_folder
from ingest.loaders.quantities import LoadResult


def test_dispatch_recognizes_quantity_prefix(tmp_path: Path) -> None:
    assert dispatch(tmp_path / "HKQuantityTypeIdentifierHeartRate_x.csv") == "quantities"


def test_dispatch_recognizes_category_prefix(tmp_path: Path) -> None:
    assert dispatch(tmp_path / "HKCategoryTypeIdentifierSleepAnalysis_x.csv") == "categories"


def test_dispatch_returns_none_for_unknown(tmp_path: Path) -> None:
    assert dispatch(tmp_path / "random.csv") is None
    assert dispatch(tmp_path / "workouts.csv") is None


def test_load_folder_raises_on_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_folder(tmp_path / "does-not-exist")


def _fake_ok_loader(calls: list[Path]):
    def _load(path: Path, engine=None) -> LoadResult:
        calls.append(path)
        return LoadResult(path=path, sha256="abc", rows_read=10, rows_inserted=10, skipped=False)

    return _load


def test_load_folder_dispatches_to_correct_loaders(tmp_path: Path) -> None:
    (tmp_path / "HKQuantityTypeIdentifierHeartRate_a.csv").write_text("hdr\n")
    (tmp_path / "HKQuantityTypeIdentifierRestingHeartRate_b.csv").write_text("hdr\n")
    (tmp_path / "HKCategoryTypeIdentifierSleep_c.csv").write_text("hdr\n")
    (tmp_path / "other.csv").write_text("hdr\n")

    q_calls: list[Path] = []
    c_calls: list[Path] = []
    result = load_folder(
        tmp_path,
        quantities_loader=_fake_ok_loader(q_calls),
        categories_loader=_fake_ok_loader(c_calls),
    )

    assert {p.name for p in q_calls} == {
        "HKQuantityTypeIdentifierHeartRate_a.csv",
        "HKQuantityTypeIdentifierRestingHeartRate_b.csv",
    }
    assert {p.name for p in c_calls} == {"HKCategoryTypeIdentifierSleep_c.csv"}
    assert len(result.loaded) == 3
    assert len(result.skipped) == 1  # only the unrecognized "other.csv"
    assert result.total_rows_inserted == 30


def test_load_folder_walks_subdirectories(tmp_path: Path) -> None:
    sub = tmp_path / "nested" / "deep"
    sub.mkdir(parents=True)
    (sub / "HKQuantityTypeIdentifierVO2Max_x.csv").write_text("hdr\n")

    calls: list[Path] = []
    result = load_folder(tmp_path, quantities_loader=_fake_ok_loader(calls))

    assert len(calls) == 1
    assert calls[0].name == "HKQuantityTypeIdentifierVO2Max_x.csv"
    assert len(result.loaded) == 1


def test_load_folder_continues_past_errors(tmp_path: Path) -> None:
    (tmp_path / "HKQuantityTypeIdentifierGood_a.csv").write_text("hdr\n")
    (tmp_path / "HKQuantityTypeIdentifierBad_b.csv").write_text("hdr\n")
    (tmp_path / "HKQuantityTypeIdentifierGood_c.csv").write_text("hdr\n")

    def flaky(path: Path, engine=None) -> LoadResult:
        if "Bad" in path.name:
            raise RuntimeError("boom")
        return LoadResult(path=path, sha256="x", rows_read=1, rows_inserted=1, skipped=False)

    result = load_folder(tmp_path, quantities_loader=flaky)

    assert len(result.loaded) == 2
    assert len(result.errors) == 1
    assert result.errors[0][0].name == "HKQuantityTypeIdentifierBad_b.csv"
    assert isinstance(result.errors[0][1], RuntimeError)


def test_batch_result_counts(tmp_path: Path) -> None:
    (tmp_path / "HKQuantityTypeIdentifierA_x.csv").write_text("hdr\n")
    (tmp_path / "HKQuantityTypeIdentifierB_x.csv").write_text("hdr\n")

    def mixed(path: Path, engine=None) -> LoadResult:
        # First one is "already loaded", second is new.
        skipped = "A_x" in path.name
        return LoadResult(
            path=path,
            sha256="y",
            rows_read=0 if skipped else 5,
            rows_inserted=0 if skipped else 5,
            skipped=skipped,
        )

    result = load_folder(tmp_path, quantities_loader=mixed)
    assert result.files_loaded == 1
    assert result.files_already_loaded == 1
    assert result.total_rows_inserted == 5
