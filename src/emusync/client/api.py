from __future__ import annotations

from urllib.parse import quote

import httpx

from emusync.model import Manifest, Version

CONNECT_TIMEOUT = 3.0


class ApiError(Exception):
    pass


class Offline(ApiError):
    pass


class Unauthorized(ApiError):
    pass


class PushRejected(ApiError):
    def __init__(self, head: int):
        super().__init__(f"server head moved to {head}")
        self.head = head


class ServerError(ApiError):
    pass


class Api:
    def __init__(self, http: httpx.Client):
        self.http = http

    @classmethod
    def connect(cls, server_url: str, token: str, timeout: float = 10.0) -> Api:
        return cls(
            httpx.Client(
                base_url=server_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT)),
            )
        )

    def check(self) -> None:
        self._request("GET", "/slots")

    def head(self, slot: str) -> Version | None:
        response = self._request("GET", f"/slots/{_quote(slot)}/versions/head", allow_404=True)
        return None if response.status_code == 404 else Version.from_dict(response.json())

    def history(self, slot: str) -> list[Version]:
        response = self._request("GET", f"/slots/{_quote(slot)}/versions")
        return [Version.from_dict(d) for d in response.json()]

    def missing(self, hashes: list[str]) -> list[str]:
        return self._request("POST", "/blobs/missing", json={"hashes": hashes}).json()["missing"]

    def upload(self, sha256: str, data: bytes) -> None:
        self._request("PUT", f"/blobs/{sha256}", content=data)

    def download(self, sha256: str) -> bytes:
        return self._request("GET", f"/blobs/{sha256}").content

    def create_version(
        self, slot: str, base: int, manifest: Manifest, label: str | None = None
    ) -> Version:
        body = {"base": base, "files": manifest.to_list(), "label": label}
        response = self._request("POST", f"/slots/{_quote(slot)}/versions", json=body)
        return Version.from_dict(response.json())

    def restore(self, slot: str, number: int, base: int) -> Version:
        body = {"version": number, "base": base}
        response = self._request("POST", f"/slots/{_quote(slot)}/restore", json=body)
        return Version.from_dict(response.json())

    def _request(self, method: str, url: str, allow_404: bool = False, **kwargs) -> httpx.Response:
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.TransportError as err:
            raise Offline(str(err)) from err
        if response.status_code == 401:
            raise Unauthorized("server rejected the token, run `emusync login`")
        if response.status_code == 409:
            raise PushRejected(response.json()["head"])
        if response.status_code == 404 and allow_404:
            return response
        if response.status_code >= 400:
            raise ServerError(f"{method} {url}: {response.status_code} {response.text}")
        return response


def _quote(slot: str) -> str:
    return quote(slot, safe="/")
