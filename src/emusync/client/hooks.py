from __future__ import annotations

import os
import re
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

MARKER = "# emusync-hook"
INIT_RE = re.compile(r'^\s*emulatorInit\s+"([^"]+)"')
VARIABLE_RE = re.compile(r"^\$(?:(\w+)|\{(\w+)\})$")
POST_RE = re.compile(r"^\s*cloud_sync_uploadForced\b")
CLOUDSYNC_RE = re.compile(r'^cloud_sync_status="?true"?\s*$', re.MULTILINE)


@dataclass(frozen=True)
class LauncherStatus:
    path: Path
    emulator: str | None
    hooked: bool


def emudeck_settings_path() -> Path:
    return Path.home() / ".config" / "EmuDeck" / "settings.sh"


def hook_line(exe: Path, emulator: str) -> str:
    quoted = shlex.quote(str(exe))
    return f"[ -x {quoted} ] && {quoted} sync --emulator {shlex.quote(emulator)}  {MARKER}"


def launcher_emulator(text: str) -> str | None:
    found = _find_init(text.splitlines())
    return found[1] if found else None


def _find_init(lines: list[str]) -> tuple[int, str] | None:
    for index, line in enumerate(lines):
        match = INIT_RE.match(line)
        if match:
            name = _resolve(match.group(1), lines[:index])
            return (index, name) if name else None
    return None


def _resolve(argument: str, preceding: list[str]) -> str | None:
    variable = VARIABLE_RE.match(argument)
    if not variable:
        return argument
    name = variable.group(1) or variable.group(2)
    assignment = re.compile(rf'^\s*{name}="([^"$`\\]+)"')
    for line in reversed(preceding):
        match = assignment.match(line)
        if match:
            return match.group(1)
    return None


def add_hooks(text: str, exe: Path) -> str | None:
    lines = strip_hooks(text).splitlines()
    found = _find_init(lines)
    if found is None:
        return None
    init_index, emulator = found
    line = hook_line(exe, emulator)
    lines.insert(init_index + 1, line)
    post_index = next((i for i, existing in enumerate(lines) if POST_RE.match(existing)), None)
    if post_index is None:
        lines.append(line)
    else:
        lines.insert(post_index, line)
    return _join(lines, text)


def strip_hooks(text: str) -> str:
    return _join([line for line in text.splitlines() if not line.endswith(MARKER)], text)


def _join(lines: list[str], original: str) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + ("\n" if original.endswith("\n") else "")


def _replace_text(path: Path, text: str) -> None:
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(text)
        shutil.copymode(path, temp)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def install(launchers_dir: Path, exe: Path) -> list[Path]:
    changed = []
    for path in sorted(launchers_dir.glob("*.sh")):
        text = path.read_text()
        hooked = add_hooks(text, exe)
        if hooked is not None and hooked != text:
            _replace_text(path, hooked)
            changed.append(path)
    return changed


def remove(launchers_dir: Path) -> list[Path]:
    changed = []
    for path in sorted(launchers_dir.glob("*.sh")):
        text = path.read_text()
        stripped = strip_hooks(text)
        if stripped != text:
            _replace_text(path, stripped)
            changed.append(path)
    return changed


def status(launchers_dir: Path) -> list[LauncherStatus]:
    return [
        LauncherStatus(path, launcher_emulator(text), MARKER in text)
        for path in sorted(launchers_dir.glob("*.sh"))
        for text in [path.read_text()]
    ]


def cloudsync_enabled(settings_file: Path) -> bool:
    return settings_file.is_file() and bool(CLOUDSYNC_RE.search(settings_file.read_text()))
