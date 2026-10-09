import io
import subprocess

import pytest

from emusync.client import prompt
from emusync.client.prompt import NullPrompter, TtyPrompter, ZenityPrompter, describe
from emusync.client.sync import Choice
from emusync.model import FileEntry, Manifest, Version

LOCAL = Manifest.of([FileEntry("a.srm", "1" * 64, 1, 1_760_000_000.0)])
SERVER = Version(7, "steamdeck", "2026-10-08T19:02:00+00:00", None, LOCAL)


def test_describe_mentions_slot_device_and_times():
    text = describe("pcsx2/saves", LOCAL, SERVER)
    assert "pcsx2/saves" in text
    assert "steamdeck" in text
    assert "version 7" in text


@pytest.mark.parametrize(
    "answer, expected", [("t", Choice.LOCAL), ("S", Choice.SERVER), ("", None), ("x\nt", Choice.LOCAL)]
)
def test_tty_prompter(answer, expected):
    answers = iter(answer.split("\n"))
    out = io.StringIO()
    result = TtyPrompter(read=lambda _p: next(answers), out=out).choose("a/saves", LOCAL, SERVER)
    assert result is expected
    assert "a/saves" in out.getvalue()


def completed(code, stdout=""):
    return subprocess.CompletedProcess([], code, stdout=stdout)


@pytest.mark.parametrize(
    "result, expected",
    [
        (completed(0), Choice.LOCAL),
        (completed(1, "Keep server\n"), Choice.SERVER),
        (completed(1, ""), None),
        (completed(5, ""), None),
    ],
)
def test_zenity_prompter_maps_buttons(result, expected):
    calls = []

    def run(args):
        calls.append(args)
        return result

    assert ZenityPrompter(run=run).choose("a/saves", LOCAL, SERVER) is expected
    assert calls[0][0] == "zenity"
    assert "--extra-button=Keep server" in calls[0]


def test_null_prompter_never_chooses():
    assert NullPrompter().choose("a/saves", LOCAL, SERVER) is None


def test_pick_prompter(monkeypatch):
    monkeypatch.setattr(prompt.sys.stdin, "isatty", lambda: True, raising=False)
    assert isinstance(prompt.pick_prompter(), TtyPrompter)

    monkeypatch.setattr(prompt.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(prompt.shutil, "which", lambda name: "/usr/bin/zenity")
    monkeypatch.setenv("DISPLAY", ":0")
    assert isinstance(prompt.pick_prompter(), ZenityPrompter)

    monkeypatch.delenv("DISPLAY")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert isinstance(prompt.pick_prompter(), NullPrompter)
