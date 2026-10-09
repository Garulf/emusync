import pytest
from fastapi.testclient import TestClient

from emusync.scan import sha256_bytes
from emusync.server.app import create_app

SLOT = "retroarch/saves"


def upload(client, content: bytes) -> dict:
    sha = sha256_bytes(content)
    assert client.post("/blobs/missing", json={"hashes": [sha]}).json() == {"missing": [sha]}
    assert client.put(f"/blobs/{sha}", content=content).status_code == 204
    return {"path": "Pokemon Emerald.srm", "sha256": sha, "size": len(content), "mtime": 1.0}


def create(client, base, files, label=None):
    return client.post(f"/slots/{SLOT}/versions", json={"base": base, "files": files, "label": label})


def test_health_needs_no_token(store):
    assert TestClient(create_app(store)).get("/health").json() == {"status": "ok"}


def test_requests_without_valid_token_are_rejected(store):
    client = TestClient(create_app(store))
    assert client.get("/slots").status_code == 401
    assert client.get("/slots", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_push_and_fetch_round_trip(client_for):
    deck = client_for("deck")
    entry = upload(deck, b"save-data")
    created = create(deck, 0, [entry])
    assert created.status_code == 201
    assert created.json()["number"] == 1
    assert created.json()["device"] == "deck"
    assert deck.get("/slots").json() == [{"name": SLOT, "head": 1}]
    head = deck.get(f"/slots/{SLOT}/versions/head").json()
    assert head["files"] == [entry]
    assert deck.get(f"/blobs/{entry['sha256']}").content == b"save-data"


def test_stale_base_returns_409_with_head(client_for):
    deck, pc = client_for("deck"), client_for("pc")
    create(deck, 0, [upload(deck, b"one")])
    response = create(pc, 0, [upload(pc, b"two")])
    assert response.status_code == 409
    assert response.json()["head"] == 1


def test_missing_blob_returns_400_with_list(client_for):
    deck = client_for("deck")
    entry = {"path": "a.srm", "sha256": "e" * 64, "size": 1, "mtime": 1.0}
    response = create(deck, 0, [entry])
    assert response.status_code == 400
    assert response.json()["missing"] == ["e" * 64]


def test_unsafe_path_returns_400(client_for):
    deck = client_for("deck")
    entry = upload(deck, b"x") | {"path": "../../.bashrc"}
    assert create(deck, 0, [entry]).status_code == 400


def test_clients_cannot_forge_restore_labels(client_for):
    deck = client_for("deck")
    assert create(deck, 0, [upload(deck, b"x")], label="restore-of:1").status_code == 400


def test_blob_hash_mismatch_returns_400(client_for):
    assert client_for("deck").put(f"/blobs/{'0' * 64}", content=b"nope").status_code == 400


def test_history_restore_and_lookups(client_for):
    deck = client_for("deck")
    first = upload(deck, b"one")
    create(deck, 0, [first])
    create(deck, 1, [upload(deck, b"two")], label="conflict-lost")
    history = deck.get(f"/slots/{SLOT}/versions").json()
    assert [(v["number"], v["label"]) for v in history] == [(2, "conflict-lost"), (1, None)]
    assert "files" not in history[0]

    restored = deck.post(f"/slots/{SLOT}/restore", json={"version": 1, "base": 2})
    assert restored.status_code == 201
    assert restored.json()["label"] == "restore-of:1"
    assert restored.json()["files"] == [first]

    assert deck.post(f"/slots/{SLOT}/restore", json={"version": 1, "base": 0}).status_code == 409
    assert deck.post(f"/slots/{SLOT}/restore", json={"version": 9, "base": 3}).status_code == 404
    assert deck.get(f"/slots/{SLOT}/versions/abc").status_code == 404
    assert deck.get("/slots/none/saves/versions/head").status_code == 404
    assert deck.get(f"/blobs/{'f' * 64}").status_code == 404


@pytest.mark.parametrize("slot", ["dolphin/GC", "retroarch/saves/Pokemon Emerald"])
def test_slot_names_with_slashes_and_spaces_route(client_for, slot):
    deck = client_for("deck")
    entry = upload(deck, b"x")
    response = deck.post(f"/slots/{slot}/versions", json={"base": 0, "files": [entry]})
    assert response.status_code == 201
    assert deck.get(f"/slots/{slot}/versions/1").json()["number"] == 1


def test_keep_server_records_lost_copy_and_returns_restored_head(client_for):
    deck = client_for("deck")
    first = upload(deck, b"one")
    create(deck, 0, [first])
    lost = upload(deck, b"local")
    response = deck.post(f"/slots/{SLOT}/keep-server", json={"base": 1, "files": [lost]})
    assert response.status_code == 201
    assert response.json()["number"] == 3
    assert response.json()["label"] == "restore-of:1"
    assert response.json()["files"] == [first]
    history = deck.get(f"/slots/{SLOT}/versions").json()
    assert [(v["number"], v["label"]) for v in history] == [
        (3, "restore-of:1"),
        (2, "conflict-lost"),
        (1, None),
    ]


def test_keep_server_with_stale_base_returns_409(client_for):
    deck = client_for("deck")
    create(deck, 0, [upload(deck, b"one")])
    create(deck, 1, [upload(deck, b"two")])
    lost = upload(deck, b"local")
    response = deck.post(f"/slots/{SLOT}/keep-server", json={"base": 1, "files": [lost]})
    assert response.status_code == 409
    assert response.json()["head"] == 2
