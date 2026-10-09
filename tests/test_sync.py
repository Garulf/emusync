import pytest

from emusync.client.api import Api, Offline
from emusync.client.state import State
from emusync.client.sync import Outcome, SyncError, Syncer
from emusync.decide import Action
from emusync.model import TMP_SUFFIX, FileEntry, Manifest, Version

SLOT = "pcsx2/saves"


def test_push_then_pull_to_second_device(make_device):
    deck, pc = make_device("deck"), make_device("pc")
    deck.write("Mcd001.ps2", b"card", mtime=1000)
    deck.write("sub/extra.bin", b"x")
    assert deck.syncer.sync(SLOT, deck.root) is Outcome.PUSHED
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.PULLED
    assert pc.files() == deck.files()
    assert (pc.root / "Mcd001.ps2").stat().st_mtime == 1000


def test_changes_and_deletions_propagate(make_device):
    deck, pc = make_device("deck"), make_device("pc")
    deck.write("a.srm", b"1")
    deck.write("b.srm", b"2")
    deck.syncer.sync(SLOT, deck.root)
    pc.syncer.sync(SLOT, pc.root)
    pc.write("a.srm", b"changed")
    (pc.root / "b.srm").unlink()
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.PUSHED
    assert deck.syncer.sync(SLOT, deck.root) is Outcome.PULLED
    assert deck.files() == {"a.srm": b"changed"}


def test_unchanged_slot_creates_no_version(make_device):
    deck = make_device("deck")
    deck.write("a.srm", b"1")
    deck.syncer.sync(SLOT, deck.root)
    assert deck.syncer.sync(SLOT, deck.root) is Outcome.IN_SYNC
    assert len(deck.syncer.api.history(SLOT)) == 1
    assert deck.syncer.plan(SLOT, deck.root) is Action.NOTHING


def test_identical_content_on_second_device_is_adopted_without_prompt(make_device):
    deck, pc = make_device("deck"), make_device("pc")
    deck.write("a.srm", b"same")
    pc.write("a.srm", b"same")
    deck.syncer.sync(SLOT, deck.root)
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.ADOPTED
    assert len(pc.syncer.api.history(SLOT)) == 1
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.IN_SYNC


def test_emptied_folder_is_not_pushed(make_device):
    deck = make_device("deck")
    deck.write("a.srm", b"1")
    deck.syncer.sync(SLOT, deck.root)
    (deck.root / "a.srm").unlink()
    assert deck.syncer.sync(SLOT, deck.root) is Outcome.SKIPPED_EMPTY
    assert deck.syncer.api.head(SLOT).number == 1


def test_offline_leaves_state_untouched(tmp_path):
    root = tmp_path / "saves"
    root.mkdir()
    (root / "a.srm").write_bytes(b"1")
    state = State(tmp_path / "state.json")
    syncer = Syncer(Api.connect("http://127.0.0.1:9", "t", timeout=2.0), state, None)
    assert syncer.sync(SLOT, root) is Outcome.OFFLINE
    assert state.base(SLOT) is None


def test_interrupted_pull_is_redone_next_time(make_device, monkeypatch):
    deck, pc = make_device("deck"), make_device("pc")
    deck.write("a.srm", b"1")
    deck.write("b.srm", b"2")
    deck.syncer.sync(SLOT, deck.root)

    real_download = pc.syncer.api.download
    calls = []

    def flaky(sha):
        calls.append(sha)
        if len(calls) == 2:
            raise Offline("wifi dropped")
        return real_download(sha)

    monkeypatch.setattr(pc.syncer.api, "download", flaky)
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.OFFLINE
    assert pc.state.base(SLOT) is None

    monkeypatch.setattr(pc.syncer.api, "download", real_download)
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.PULLED
    assert pc.files() == deck.files()


def test_leftover_temp_files_are_ignored(make_device):
    deck, pc = make_device("deck"), make_device("pc")
    deck.write("a.srm", b"1")
    deck.syncer.sync(SLOT, deck.root)
    pc.write("a.srm" + TMP_SUFFIX, b"partial")
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.PULLED
    assert pc.files()["a.srm"] == b"1"


def test_unsafe_server_paths_are_never_written(make_device, monkeypatch, tmp_path):
    pc = make_device("pc")
    evil = Version(
        1,
        "evil",
        "2026-10-08T00:00:00+00:00",
        None,
        Manifest.of([FileEntry("../../escaped.txt", "a" * 64, 1, 1.0)]),
    )
    monkeypatch.setattr(pc.syncer.api, "head", lambda slot: evil)
    with pytest.raises(SyncError):
        pc.syncer.sync(SLOT, pc.root)
    assert not (tmp_path / "escaped.txt").exists()


def test_push_race_with_identical_content_adopts(make_device, monkeypatch):
    deck, pc = make_device("deck"), make_device("pc")
    deck.write("a.srm", b"1")
    deck.syncer.sync(SLOT, deck.root)
    pc.syncer.sync(SLOT, pc.root)
    stale_head = pc.syncer.api.head(SLOT)

    deck.write("a.srm", b"2")
    deck.syncer.sync(SLOT, deck.root)
    pc.write("a.srm", b"2")

    real_head = pc.syncer.api.head
    heads = iter([stale_head])
    monkeypatch.setattr(pc.syncer.api, "head", lambda slot: next(heads, None) or real_head(slot))
    assert pc.syncer.sync(SLOT, pc.root) is Outcome.ADOPTED
    assert pc.state.base(SLOT).version == 2
