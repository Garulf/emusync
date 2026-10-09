import httpx
import pytest

from emusync.client.api import Api, Offline, PushRejected, ServerError, Unauthorized
from emusync.model import FileEntry, Manifest
from emusync.scan import sha256_bytes

SLOT = "dolphin/GC"


def manifest_of(api: Api, content: bytes) -> Manifest:
    sha = sha256_bytes(content)
    if api.missing([sha]):
        api.upload(sha, content)
    return Manifest.of([FileEntry("MemoryCardA.USA.raw", sha, len(content), 5.0)])


def test_head_of_unknown_slot_is_none(client_for):
    assert Api(client_for("deck")).head(SLOT) is None


def test_push_pull_round_trip(client_for):
    api = Api(client_for("deck"))
    api.check()
    manifest = manifest_of(api, b"card")
    created = api.create_version(SLOT, 0, manifest)
    assert created.number == 1
    assert api.head(SLOT).manifest == manifest
    assert api.download(manifest.files[0].sha256) == b"card"
    assert [v.number for v in api.history(SLOT)] == [1]


def test_stale_push_raises_with_head(client_for):
    deck, pc = Api(client_for("deck")), Api(client_for("pc"))
    deck.create_version(SLOT, 0, manifest_of(deck, b"one"))
    with pytest.raises(PushRejected) as err:
        pc.create_version(SLOT, 0, manifest_of(pc, b"two"))
    assert err.value.head == 1


def test_restore(client_for):
    api = Api(client_for("deck"))
    first = api.create_version(SLOT, 0, manifest_of(api, b"one"))
    api.create_version(SLOT, 1, manifest_of(api, b"two"), label="conflict-lost")
    restored = api.restore(SLOT, 1, base=2)
    assert restored.manifest == first.manifest
    assert restored.label == "restore-of:1"


def test_bad_token_raises_unauthorized(store):
    from fastapi.testclient import TestClient

    from emusync.server.app import create_app

    client = TestClient(create_app(store), headers={"Authorization": "Bearer nope"})
    with pytest.raises(Unauthorized):
        Api(client).check()


def test_server_errors_are_wrapped(client_for):
    api = Api(client_for("deck"))
    with pytest.raises(ServerError):
        api.upload("0" * 64, b"mismatch")


def test_unreachable_server_is_offline():
    api = Api.connect("http://127.0.0.1:9", "token", timeout=2.0)
    with pytest.raises(Offline):
        api.check()


def api_answering(response: httpx.Response) -> Api:
    transport = httpx.MockTransport(lambda request: response)
    return Api(httpx.Client(transport=transport, base_url="http://test"))


def test_redirect_is_a_server_error():
    api = api_answering(httpx.Response(302, headers={"Location": "http://elsewhere/"}))
    with pytest.raises(ServerError):
        api.check()


def test_non_json_success_body_is_a_server_error():
    api = api_answering(httpx.Response(200, text="<html>login</html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(ServerError):
        api.history("a/saves")


def test_conflict_without_head_is_a_server_error():
    api = api_answering(httpx.Response(409, json={}))
    with pytest.raises(ServerError):
        api.create_version("a/saves", 0, Manifest.of([]))
