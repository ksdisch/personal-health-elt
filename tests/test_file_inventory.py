"""Tests for ingest.file_inventory — pure Python, no DB required."""

from pathlib import Path

from ingest.file_inventory import FileEntry, hash_file, scan, unseen


def test_hash_file_is_deterministic(tmp_path: Path) -> None:
    f = tmp_path / "sample.csv"
    f.write_bytes(b"metric,value\nresting_hr,62\n")
    assert hash_file(f) == hash_file(f)


def test_hash_file_differs_across_contents(tmp_path: Path) -> None:
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert hash_file(a) != hash_file(b)


def test_scan_returns_only_csvs_sorted(tmp_path: Path) -> None:
    (tmp_path / "keep.csv").write_bytes(b"csv")
    (tmp_path / "skip.txt").write_bytes(b"text")
    (tmp_path / "also.csv").write_bytes(b"csv2")
    names = [e.path.name for e in scan(tmp_path)]
    assert names == ["also.csv", "keep.csv"]


def test_scan_handles_empty_and_missing_dirs(tmp_path: Path) -> None:
    assert scan(tmp_path) == []
    assert scan(tmp_path / "does-not-exist") == []


def test_scan_populates_hashes(tmp_path: Path) -> None:
    f = tmp_path / "a.csv"
    f.write_bytes(b"payload")
    entries = scan(tmp_path)
    assert len(entries) == 1
    assert entries[0] == FileEntry(path=f, sha256=hash_file(f))


def test_unseen_filters_by_hash(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_bytes(b"one")
    (tmp_path / "b.csv").write_bytes(b"two")
    entries = scan(tmp_path)
    seen = {entries[0].sha256}
    new = unseen(entries, seen)
    assert [e.path.name for e in new] == ["b.csv"]


def test_unseen_with_no_prior_hashes_returns_all(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_bytes(b"one")
    (tmp_path / "b.csv").write_bytes(b"two")
    entries = scan(tmp_path)
    assert unseen(entries, set()) == entries


def test_unseen_with_all_known_hashes_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_bytes(b"one")
    entries = scan(tmp_path)
    all_hashes = {e.sha256 for e in entries}
    assert unseen(entries, all_hashes) == []
