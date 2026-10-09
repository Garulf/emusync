import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from emusync import cli
from emusync.client.api import Api
from emusync.client.sync import Syncer
from emusync.server.app import create_app
from emusync.server.store import Store


@pytest.fixture
def env(tmp_path, monkeypatch, store):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    app = create_app(store)

    def connect(cls, server_url, token, timeout=10.0):
        return cls(TestClient(app, headers={"Authorization": f"Bearer {token}"}))

    monkeypatch.setattr(Api, "connect", classmethod(connect))
    emudeck = tmp_path / "Emulation"
    saves = emudeck / "saves" / "pcsx2" / "saves"
    saves.mkdir(parents=True)
    (emudeck / "saves" / "retroarch" / "saves").mkdir(parents=True)
    config_file = tmp_path / "config" / "emusync" / "config.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(f'emudeck_root = "{emudeck}"\n')
    token = store.add_device("deck")
    assert cli.main(["login", "--", "http://saves.lan:8080", token]) == 0
    return SimpleNamespace(saves=saves, store=store, tmp=tmp_path)


def test_login_reports_connection(capsys, env):
    assert "Connected" in capsys.readouterr().out


def test_commands_require_login(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    assert cli.main(["status"]) == 1
    assert "emusync login" in capsys.readouterr().err


def test_sync_status_and_history(env, capsys):
    (env.saves / "Mcd001.ps2").write_bytes(b"card")
    assert cli.main(["sync"]) == 0
    assert "pcsx2/saves: pushed" in capsys.readouterr().out
    assert cli.main(["status"]) == 0
    assert "pcsx2/saves" in capsys.readouterr().out
    assert cli.main(["history", "pcsx2/saves"]) == 0
    out = capsys.readouterr().out
    assert "1" in out and "deck" in out


def test_sync_filters_by_emulator_case_insensitively(env, capsys):
    (env.saves / "Mcd001.ps2").write_bytes(b"card")
    assert cli.main(["sync", "--emulator", "PCSX2"]) == 0
    out = capsys.readouterr().out
    assert "pcsx2/saves" in out
    assert "retroarch" not in out


def test_unknown_slot_fails(env, capsys):
    assert cli.main(["sync", "nope/saves"]) == 1
    assert "unknown slot" in capsys.readouterr().err


def test_restore_brings_back_old_content(env):
    card = env.saves / "Mcd001.ps2"
    card.write_bytes(b"old")
    cli.main(["sync"])
    card.write_bytes(b"new")
    cli.main(["sync"])
    assert cli.main(["restore", "pcsx2/saves", "1"]) == 0
    assert card.read_bytes() == b"old"


def test_run_syncs_around_the_command_and_keeps_exit_code(env):
    card = env.saves / "Mcd001.ps2"
    script = f"open({str(card)!r}, 'wb').write(b'played'); raise SystemExit(3)"
    assert cli.main(["run", "pcsx2", "--", sys.executable, "-c", script]) == 3
    head = env.store.head("pcsx2/saves")
    assert head is not None and head.number == 1


def test_offline_sync_does_not_fail_the_launch(env, monkeypatch, capsys):
    monkeypatch.undo()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(env.tmp / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(env.tmp / "state"))
    config = env.tmp / "config" / "emusync" / "config.toml"
    config.write_text(config.read_text().replace("http://saves.lan:8080", "http://127.0.0.1:9"))
    (env.saves / "Mcd001.ps2").write_bytes(b"card")
    assert cli.main(["sync"]) == 0
    captured = capsys.readouterr()
    assert "pcsx2/saves: offline" in captured.out
    assert "server unreachable" in captured.err


def test_filesystem_error_on_one_slot_does_not_stop_the_others(env, monkeypatch, capsys):
    (env.saves / "Mcd001.ps2").write_bytes(b"card")
    real_sync = Syncer.sync

    def sync(self, slot, root):
        if slot == "pcsx2/saves":
            raise OSError("disk full")
        return real_sync(self, slot, root)

    monkeypatch.setattr(Syncer, "sync", sync)
    assert cli.main(["sync"]) == 1
    captured = capsys.readouterr()
    assert "pcsx2/saves: disk full" in captured.err
    assert "retroarch/saves" in captured.out


def test_admin_device_commands(tmp_path, capsys):
    data = str(tmp_path / "data")
    assert cli.main(["admin", "device", "add", "deck", "--data", data]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    store = Store(tmp_path / "data")
    assert store.authenticate(token) == "deck"
    store.close()
    assert cli.main(["admin", "device", "list", "--data", data]) == 0
    assert "deck" in capsys.readouterr().out
    assert cli.main(["admin", "device", "revoke", "deck", "--data", data]) == 0
    assert cli.main(["admin", "device", "revoke", "deck", "--data", data]) == 1


def test_run_without_config_still_runs_the_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    script = "raise SystemExit(5)"
    assert cli.main(["run", "pcsx2", "--", sys.executable, "-c", script]) == 5
    assert "emusync login" in capsys.readouterr().err


def test_run_with_corrupt_state_still_runs_the_command(env, capsys):
    state_file = env.tmp / "state" / "emusync" / "state.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("not json")
    script = "raise SystemExit(4)"
    assert cli.main(["run", "pcsx2", "--", sys.executable, "-c", script]) == 4
    assert "sync skipped" in capsys.readouterr().err
