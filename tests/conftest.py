import pytest
from fastapi.testclient import TestClient

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
