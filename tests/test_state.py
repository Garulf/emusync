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
