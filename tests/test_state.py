import pytest

from emusync.client.state import State
from emusync.decide import Base
from emusync.model import FileEntry, Manifest


def test_unknown_slot_has_no_base(tmp_path):
    assert State(tmp_path / "state.json").base("a/saves") is None


def test_base_persists_across_instances(tmp_path):
    path = tmp_path / "nested" / "state.json"
    base = Base(4, Manifest.of([FileEntry("a.srm", "1" * 64, 2, 3.0)]))
    State(path).set_base("a/saves", base)
    assert State(path).base("a/saves") == base
    assert not path.with_name("state.json.tmp").exists()


@pytest.mark.parametrize("content", ["not json", "{}", '{"slots": []}', '{"slots": {"a/saves": 1}}'])
def test_corrupt_state_starts_empty_and_is_set_aside(tmp_path, capsys, content):
    path = tmp_path / "state.json"
    path.write_text(content)
    state = State(path)
    assert state.base("a/saves") is None
    assert not path.exists()
    assert path.with_name("state.json.corrupt").read_text() == content
    assert "state.json.corrupt" in capsys.readouterr().err


def test_newer_corrupt_state_replaces_older_one(tmp_path):
    path = tmp_path / "state.json"
    path.with_name("state.json.corrupt").write_text("old")
    path.write_text("new")
    State(path)
    assert path.with_name("state.json.corrupt").read_text() == "new"
