import pytest

from emusync.model import FileEntry, Manifest, Version, is_safe_relative


def entry(path, sha="a" * 64, mtime=1.0):
    return FileEntry(path=path, sha256=sha, size=3, mtime=mtime)


@pytest.mark.parametrize("path", ["a.srm", "dir/a.srm", "Pokemon Emerald.srm", ".hidden"])
def test_safe_relative_accepts_plain_paths(path):
    assert is_safe_relative(path)


@pytest.mark.parametrize(
    "path", ["", "/etc/passwd", "../x", "a/../../x", "a//b", "./a", "a\\b", "a/"]
)
def test_safe_relative_rejects_escapes_and_odd_forms(path):
    assert not is_safe_relative(path)


def test_manifest_sorts_and_compares_content_only():
    one = Manifest.of([entry("b", mtime=1), entry("a", mtime=1)])
    two = Manifest.of([entry("a", mtime=99), entry("b", mtime=50)])
    assert [f.path for f in one.files] == ["a", "b"]
    assert one.same_content(two)


def test_manifest_detects_changed_hash_and_missing_file():
    base = Manifest.of([entry("a"), entry("b")])
    assert not base.same_content(Manifest.of([entry("a"), entry("b", sha="b" * 64)]))
    assert not base.same_content(Manifest.of([entry("a")]))


def test_manifest_helpers():
    m = Manifest.of([entry("a", sha="1" * 64, mtime=5), entry("b", sha="2" * 64, mtime=9)])
    assert m.hashes() == {"1" * 64, "2" * 64}
    assert m.latest_mtime() == 9
    assert m.by_path()["a"].mtime == 5
    assert Manifest.empty().is_empty()
    assert Manifest.empty().latest_mtime() is None
    assert Manifest.from_list(m.to_list()) == m


def test_version_round_trip_and_summary():
    v = Version(3, "deck", "2026-10-08T10:00:00+00:00", "conflict-lost", Manifest.of([entry("a")]))
    assert Version.from_dict(v.to_dict()) == v
    summary = Version.from_dict(v.to_dict(with_files=False))
    assert summary.manifest.is_empty()
    assert summary.label == "conflict-lost"
