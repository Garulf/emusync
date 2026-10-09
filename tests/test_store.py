import os
import time

import pytest

from emusync.model import FileEntry, Manifest
from emusync.scan import sha256_bytes
from emusync.server.store import (
    DeviceExists,
    InvalidInput,
    MissingBlobs,
    Store,
    UnknownVersion,
    VersionConflict,
)

SLOT = "pcsx2/saves"


def manifest_for(store, content: bytes, path="Mcd001.ps2") -> Manifest:
    sha = sha256_bytes(content)
    store.put_blob(sha, content)
    return Manifest.of([FileEntry(path, sha, len(content), 1.0)])


def push(store, content: bytes, base: int, label=None):
    return store.create_version(SLOT, base, manifest_for(store, content), "deck", label)


def test_devices_lifecycle(store):
    token = store.add_device("deck")
    assert store.authenticate(token) == "deck"
    assert store.authenticate("wrong") is None
    with pytest.raises(DeviceExists):
        store.add_device("deck")
    assert store.revoke_device("deck") is True
    assert store.authenticate(token) is None
    assert store.list_devices()[0]["revoked"] is True
    new_token = store.add_device("deck")
    assert store.authenticate(new_token) == "deck"


def test_first_push_creates_version_one(store):
    v = push(store, b"card", base=0)
    assert v.number == 1
    assert v.device == "deck"
    assert store.head(SLOT).manifest == v.manifest
    assert store.list_slots() == [(SLOT, 1)]


def test_unknown_slot_has_no_head(store):
    assert store.head("nope/saves") is None


def test_stale_base_is_rejected_with_current_head(store):
    push(store, b"one", base=0)
    push(store, b"two", base=1)
    with pytest.raises(VersionConflict) as err:
        push(store, b"three", base=1)
    assert err.value.head == 2


def test_version_requires_uploaded_blobs(store):
    missing = Manifest.of([FileEntry("a.srm", "f" * 64, 1, 1.0)])
    with pytest.raises(MissingBlobs) as err:
        store.create_version(SLOT, 0, missing, "deck")
    assert err.value.hashes == ["f" * 64]


@pytest.mark.parametrize("bad_path", ["../../.bashrc", "/etc/passwd", "a/../../b"])
def test_unsafe_manifest_paths_are_rejected(store, bad_path):
    m = manifest_for(store, b"x", path="ok")
    bad = Manifest.of([FileEntry(bad_path, m.files[0].sha256, 1, 1.0)])
    with pytest.raises(InvalidInput):
        store.create_version(SLOT, 0, bad, "deck")


def test_unsafe_slot_names_are_rejected(store):
    with pytest.raises(InvalidInput):
        store.create_version("../x", 0, Manifest.empty(), "deck")


def test_blob_upload_checks_hash(store):
    with pytest.raises(InvalidInput):
        store.put_blob("0" * 64, b"not matching")
    sha = sha256_bytes(b"ok")
    assert store.missing_blobs([sha]) == [sha]
    store.put_blob(sha, b"ok")
    assert store.missing_blobs([sha]) == []
    assert store.blob_path(sha).read_bytes() == b"ok"


def test_restore_copies_old_version_as_new_head(store):
    first = push(store, b"one", base=0)
    push(store, b"two", base=1)
    restored = store.restore(SLOT, 1, base=2, device="pc")
    assert restored.number == 3
    assert restored.label == "restore-of:1"
    assert restored.manifest == first.manifest
    with pytest.raises(UnknownVersion):
        store.restore(SLOT, 99, base=3, device="pc")
    with pytest.raises(VersionConflict):
        store.restore(SLOT, 1, base=1, device="pc")


def test_history_is_newest_first_with_labels(store):
    push(store, b"one", base=0)
    push(store, b"two", base=1, label="conflict-lost")
    history = store.history(SLOT)
    assert [(v.number, v.label) for v in history] == [(2, "conflict-lost"), (1, None)]
    assert all(v.manifest.is_empty() for v in history)


def test_retention_prunes_versions_and_old_unreferenced_blobs(tmp_path):
    store = Store(tmp_path / "data", keep_versions=2, blob_grace_seconds=60)
    first = push(store, b"one", base=0)
    old_blob = store.blob_path(first.manifest.files[0].sha256)
    os.utime(old_blob, (time.time() - 3600, time.time() - 3600))
    push(store, b"two", base=1)
    push(store, b"three", base=2)
    assert store.version(SLOT, 1) is None
    assert store.version(SLOT, 2) is not None
    assert not old_blob.exists()
    store.close()


def test_gc_keeps_fresh_blobs_uploaded_for_a_pending_push(tmp_path):
    store = Store(tmp_path / "data", keep_versions=1, blob_grace_seconds=3600)
    pending_sha = sha256_bytes(b"pending")
    store.put_blob(pending_sha, b"pending")
    push(store, b"one", base=0)
    push(store, b"two", base=1)
    assert store.missing_blobs([pending_sha]) == []
    pending = Manifest.of([FileEntry("a.srm", pending_sha, 7, 1.0)])
    assert store.create_version(SLOT, 2, pending, "pc").number == 3
    store.close()
