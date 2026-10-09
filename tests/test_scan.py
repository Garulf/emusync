import hashlib
import os

from emusync.model import TMP_SUFFIX
from emusync.scan import scan, sha256_bytes, sha256_file


def test_sha256_helpers(tmp_path):
    f = tmp_path / "x"
    f.write_bytes(b"abc")
    expected = hashlib.sha256(b"abc").hexdigest()
    assert sha256_bytes(b"abc") == expected
    assert sha256_file(f) == expected


def test_scan_missing_root_is_empty(tmp_path):
    assert scan(tmp_path / "nope").is_empty()


def test_scan_lists_nested_files_with_posix_paths(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.srm").write_bytes(b"1")
    (tmp_path / "sub" / "b.sav").write_bytes(b"22")
    os.utime(tmp_path / "a.srm", (100, 100))
    m = scan(tmp_path)
    assert [f.path for f in m.files] == ["a.srm", "sub/b.sav"]
    assert m.by_path()["a.srm"].mtime == 100
    assert m.by_path()["sub/b.sav"].size == 2


def test_scan_ignores_leftover_temp_files(tmp_path):
    (tmp_path / "a.srm").write_bytes(b"1")
    (tmp_path / ("a.srm" + TMP_SUFFIX)).write_bytes(b"partial")
    assert [f.path for f in scan(tmp_path).files] == ["a.srm"]


def test_scan_follows_root_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.srm").write_bytes(b"1")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert [f.path for f in scan(link).files] == ["a.srm"]
