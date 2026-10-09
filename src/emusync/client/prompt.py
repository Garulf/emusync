from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Callable, TextIO

from emusync.client.sync import Choice, Prompter
from emusync.model import Manifest, Version

KEEP_LOCAL = "Keep this device"
KEEP_SERVER = "Keep server"
SKIP = "Skip"


def describe(slot: str, local: Manifest, server: Version) -> str:
    local_time = local.latest_mtime()
    local_text = _local_time(local_time) if local_time is not None else "no files"
    server_time = datetime.fromisoformat(server.created_at).astimezone()
    return (
        f"{slot} changed on this device and on the server.\n"
        f"This device: modified {local_text}\n"
        f"Server: version {server.number} from {server.device}, "
        f"{server_time:%Y-%m-%d %H:%M}\n"
        "The copy you do not keep stays in history (emusync history)."
    )


def _local_time(timestamp: float) -> str:
    return f"{datetime.fromtimestamp(timestamp):%Y-%m-%d %H:%M}"


class TtyPrompter:
    def __init__(self, read: Callable[[str], str] = input, out: TextIO = sys.stderr):
        self.read = read
        self.out = out

    def choose(self, slot: str, local: Manifest, server: Version) -> Choice | None:
        print(describe(slot, local, server), file=self.out)
        while True:
            answer = self.read("Keep [t]his device, keep [s]erver, or Enter to skip: ")
            answer = answer.strip().lower()
            if answer == "":
                return None
            if answer == "t":
                return Choice.LOCAL
            if answer == "s":
                return Choice.SERVER


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=False)


class ZenityPrompter:
    def __init__(self, run: Callable[[list[str]], subprocess.CompletedProcess] = _run):
        self.run = run

    def choose(self, slot: str, local: Manifest, server: Version) -> Choice | None:
        result = self.run(
            [
                "zenity",
                "--question",
                "--title=emusync",
                "--width=420",
                f"--text={describe(slot, local, server)}",
                f"--ok-label={KEEP_LOCAL}",
                f"--cancel-label={SKIP}",
                f"--extra-button={KEEP_SERVER}",
            ]
        )
        if result.returncode == 0:
            return Choice.LOCAL
        if result.stdout.strip() == KEEP_SERVER:
            return Choice.SERVER
        return None


class NullPrompter:
    def choose(self, slot: str, local: Manifest, server: Version) -> Choice | None:
        return None


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def pick_prompter() -> Prompter:
    if sys.stdin.isatty():
        return TtyPrompter()
    if shutil.which("zenity") and _has_display():
        return ZenityPrompter()
    return NullPrompter()


def notify(message: str) -> None:
    print(f"emusync: {message}", file=sys.stderr)
    if not sys.stderr.isatty() and shutil.which("zenity") and _has_display():
        subprocess.Popen(
            ["zenity", "--notification", f"--text=emusync: {message}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
