import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from emusync.client.api import Api
from emusync.client.state import State
from emusync.client.sync import Syncer
from emusync.server.app import create_app
from emusync.server.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    yield s
    s.close()


@pytest.fixture
def client_for(store):
    app = create_app(store)

    def make(name: str) -> TestClient:
        token = store.add_device(name)
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    return make


class NeverAsked:
    def choose(self, slot, local, server):
        raise AssertionError(f"unexpected conflict prompt for {slot}")


@dataclass
class Device:
    root: Path
    state: State
    syncer: Syncer

    def write(self, path: str, data: bytes, mtime: float | None = None) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if mtime is not None:
            os.utime(target, (mtime, mtime))

    def files(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }


@pytest.fixture
def make_device(client_for, tmp_path):
    def make(name: str, prompter=None) -> Device:
        root = tmp_path / name / "saves"
        root.mkdir(parents=True)
        state = State(tmp_path / name / "state.json")
        syncer = Syncer(Api(client_for(name)), state, prompter or NeverAsked())
        return Device(root, state, syncer)

    return make
