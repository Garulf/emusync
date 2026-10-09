import shutil
import subprocess
from pathlib import Path

import pytest

from emusync import cli
from emusync.client.hooks import (
    MARKER,
    add_hooks,
    cloudsync_enabled,
    hook_line,
    install,
    remove,
    status,
    strip_hooks,
)

FIXTURES = Path(__file__).parent / "fixtures" / "launchers"
EXE = Path("/home/deck/.local/bin/emusync")


@pytest.fixture
def launchers(tmp_path):
    target = tmp_path / "launchers"
    shutil.copytree(FIXTURES, target)
    return target


def test_hooks_wrap_the_emulator_call(launchers):
    install(launchers, EXE)
    lines = (launchers / "retroarch.sh").read_text().splitlines()
    init = lines.index('emulatorInit "retroarch"')
    assert lines[init + 1] == hook_line(EXE, "retroarch")
    post = lines.index("cloud_sync_uploadForced")
    assert lines[post - 1] == hook_line(EXE, "retroarch")
    assert lines[init + 2].startswith("flatpak run")


def test_emulator_name_comes_from_emulator_init(launchers):
    install(launchers, EXE)
    assert hook_line(EXE, "dolphin") in (launchers / "dolphin-emu.sh").read_text()


def test_launcher_without_cloud_sync_gets_post_hook_at_end(launchers):
    install(launchers, EXE)
    lines = (launchers / "no-cloud.sh").read_text().splitlines()
    assert lines[-1] == hook_line(EXE, "mgba")
    assert sum(MARKER in line for line in lines) == 2


def test_non_emulator_scripts_are_untouched(launchers):
    before = (launchers / "tool.sh").read_text()
    install(launchers, EXE)
    assert (launchers / "tool.sh").read_text() == before
    assert add_hooks(before, EXE) is None


def test_install_is_idempotent_and_reinstall_updates_path(launchers):
    assert len(install(launchers, EXE)) == 3
    assert install(launchers, EXE) == []
    install(launchers, Path("/opt/emusync"))
    text = (launchers / "retroarch.sh").read_text()
    assert text.count(MARKER) == 2
    assert "/opt/emusync" in text and str(EXE) not in text


def test_remove_restores_original_exactly(launchers):
    originals = {p.name: p.read_text() for p in launchers.glob("*.sh")}
    install(launchers, EXE)
    remove(launchers)
    assert {p.name: p.read_text() for p in launchers.glob("*.sh")} == originals
    assert strip_hooks("") == ""


def test_status_reports_each_launcher(launchers):
    install(launchers, EXE)
    (launchers / "dolphin-emu.sh").write_text((FIXTURES / "dolphin-emu.sh").read_text())
    report = {s.path.name: (s.emulator, s.hooked) for s in status(launchers)}
    assert report["retroarch.sh"] == ("retroarch", True)
    assert report["dolphin-emu.sh"] == ("dolphin", False)
    assert report["tool.sh"] == (None, False)


def test_hooked_scripts_are_valid_bash(launchers):
    install(launchers, EXE)
    for script in launchers.glob("*.sh"):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_hook_line_runs_sync_and_tolerates_missing_exe(tmp_path):
    log = tmp_path / "args"
    fake = tmp_path / "fake emusync"
    fake.write_text(f'#!/usr/bin/env bash\necho "$@" > "{log}"\n')
    fake.chmod(0o755)
    subprocess.run(["bash", "-c", hook_line(fake, "pcsx2")], check=True)
    assert log.read_text().strip() == "sync --emulator pcsx2"
    result = subprocess.run(
        ["bash", "-c", hook_line(tmp_path / "missing", "pcsx2") + "\necho after"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "after"


@pytest.mark.parametrize(
    "content, expected",
    [('cloud_sync_status="true"\n', True), ("cloud_sync_status=true\n", True), ('cloud_sync_status="false"\n', False)],
)
def test_cloudsync_detection(tmp_path, content, expected):
    settings = tmp_path / "settings.sh"
    settings.write_text("#!/usr/bin/env bash\n" + content)
    assert cloudsync_enabled(settings) is expected
    assert cloudsync_enabled(tmp_path / "missing.sh") is False


def test_cli_hook_commands(launchers, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = tmp_path / ".config" / "EmuDeck" / "settings.sh"
    settings.parent.mkdir(parents=True)
    settings.write_text('cloud_sync_status="true"\n')
    args = ["--launchers", str(launchers)]
    assert cli.main(["hook", "status", *args]) == 1
    assert cli.main(["hook", "install", *args, "--exe", str(EXE)]) == 0
    captured = capsys.readouterr()
    assert "retroarch.sh" in captured.out
    assert "CloudSync" in captured.err
    assert cli.main(["hook", "status", *args]) == 0
    assert cli.main(["hook", "remove", *args]) == 0
    assert MARKER not in (launchers / "retroarch.sh").read_text()
