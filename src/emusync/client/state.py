from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from emusync.decide import Base
from emusync.model import Manifest

UNREADABLE_STATE_ERRORS = (ValueError, KeyError, TypeError, AttributeError)


class State:
    def __init__(self, path: Path):
        self.path = path
        self._bases: dict[str, Base] = self._load() if path.exists() else {}

    def base(self, slot: str) -> Base | None:
        return self._bases.get(slot)

    def set_base(self, slot: str, base: Base) -> None:
        self._bases[slot] = base
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w") as handle:
            json.dump({"slots": self._serialized()}, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    def _load(self) -> dict[str, Base]:
        try:
            return _parse(self.path.read_text())
        except UNREADABLE_STATE_ERRORS:
            self._set_aside()
            return {}

    def _set_aside(self) -> None:
        corrupt = self.path.with_name(self.path.name + ".corrupt")
        os.replace(self.path, corrupt)
        print(
            f"emusync: {self.path} was unreadable, moved it to {corrupt} and starting fresh",
            file=sys.stderr,
        )

    def _serialized(self) -> dict[str, dict]:
        return {
            slot: {"version": base.version, "files": base.manifest.to_list()}
            for slot, base in self._bases.items()
        }


def _parse(text: str) -> dict[str, Base]:
    slots = json.loads(text)["slots"]
    return {
        slot: Base(raw["version"], Manifest.from_list(raw["files"])) for slot, raw in slots.items()
    }
