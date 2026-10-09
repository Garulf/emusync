from __future__ import annotations

import json
import os
from pathlib import Path

from emusync.decide import Base
from emusync.model import Manifest


class State:
    def __init__(self, path: Path):
        self.path = path
        self._slots: dict[str, dict] = (
            json.loads(path.read_text())["slots"] if path.exists() else {}
        )

    def base(self, slot: str) -> Base | None:
        raw = self._slots.get(slot)
        if raw is None:
            return None
        return Base(raw["version"], Manifest.from_list(raw["files"]))

    def set_base(self, slot: str, base: Base) -> None:
        self._slots[slot] = {"version": base.version, "files": base.manifest.to_list()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"slots": self._slots}, indent=2))
        os.replace(tmp, self.path)
