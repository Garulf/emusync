from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

from emusync.model import is_safe_relative

STATE_FOLDERS = frozenset({"states", "statesaves"})


class ConfigError(Exception):
    pass


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "emusync" / "config.toml"


def state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "emusync" / "state.json"


@dataclass(frozen=True)
class EmulatorSettings:
    enabled: bool = True
    states: bool = False
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    server_url: str
    token: str
    emudeck_root: Path = field(default_factory=lambda: Path.home() / "Emulation")
    emulators: dict[str, EmulatorSettings] = field(default_factory=dict)
    custom_slots: dict[str, Path] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Config:
        if not path.exists():
            raise ConfigError(f"{path} not found, run `emusync login` first")
        raw = tomllib.loads(path.read_text())
        try:
            server_url, token = raw["server_url"], raw["token"]
        except KeyError as missing:
            raise ConfigError(f"{path} is missing {missing}, run `emusync login`") from None
        return cls(
            server_url=server_url,
            token=token,
            emudeck_root=Path(raw.get("emudeck_root", "~/Emulation")).expanduser(),
            emulators={
                name.lower(): _emulator_settings(section)
                for name, section in raw.get("emulators", {}).items()
            },
            custom_slots=_custom_slots(raw.get("slots", {})),
        )

    def settings_for(self, emulator: str) -> EmulatorSettings:
        return self.emulators.get(emulator.lower(), EmulatorSettings())


def _emulator_settings(section: dict) -> EmulatorSettings:
    return EmulatorSettings(
        enabled=bool(section.get("enabled", True)),
        states=bool(section.get("states", False)),
        exclude=tuple(section.get("exclude", ())),
    )


def _custom_slots(sections: dict) -> dict[str, Path]:
    slots = {}
    for name, section in sections.items():
        if not is_safe_relative(name):
            raise ConfigError(f"bad custom slot name: {name!r}")
        slots[name] = Path(section["path"]).expanduser()
    return slots


def write_login(path: Path, server_url: str, token: str) -> None:
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    raw["server_url"] = server_url.rstrip("/")
    raw["token"] = token
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        tomli_w.dump(raw, fh)
    os.chmod(path, 0o600)


def discover_slots(config: Config) -> dict[str, Path]:
    slots: dict[str, Path] = {}
    saves = config.emudeck_root / "saves"
    if saves.is_dir():
        for emulator_dir in sorted(saves.iterdir()):
            if _visible_dir(emulator_dir):
                slots.update(_emulator_slots(emulator_dir, config.settings_for(emulator_dir.name)))
    slots.update(config.custom_slots)
    return slots


def _emulator_slots(emulator_dir: Path, settings: EmulatorSettings) -> dict[str, Path]:
    if not settings.enabled:
        return {}
    slots = {}
    for folder in sorted(emulator_dir.iterdir()):
        if not _visible_dir(folder) or folder.name in settings.exclude:
            continue
        if folder.name.lower() in STATE_FOLDERS and not settings.states:
            continue
        slots[f"{emulator_dir.name}/{folder.name}"] = folder
    return slots


def _visible_dir(path: Path) -> bool:
    return not path.name.startswith(".") and path.is_dir()


def slots_for_emulator(slots: dict[str, Path], emulator: str) -> dict[str, Path]:
    wanted = emulator.lower()
    return {name: path for name, path in slots.items() if name.split("/")[0].lower() == wanted}
