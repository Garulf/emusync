from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from emusync.model import FileEntry, Manifest
from emusync.server.store import (
    InvalidInput,
    MissingBlobs,
    Store,
    UnknownVersion,
    VersionConflict,
)

CLIENT_LABELS = {None, "conflict-lost"}


class FileBody(BaseModel):
    path: str
    sha256: str
    size: int
    mtime: float


class CreateVersionBody(BaseModel):
    base: int
    files: list[FileBody]
    label: str | None = None


class RestoreBody(BaseModel):
    version: int
    base: int


class KeepServerBody(BaseModel):
    base: int
    files: list[FileBody]


class MissingBody(BaseModel):
    hashes: list[str]


def create_app(store: Store) -> FastAPI:
    app = FastAPI(title="emusync")
    bearer = HTTPBearer(auto_error=False)

    def device(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        name = store.authenticate(credentials.credentials) if credentials else None
        if name is None:
            raise HTTPException(status_code=401, detail="invalid or revoked token")
        return name

    @app.exception_handler(VersionConflict)
    def on_conflict(_request: Request, exc: VersionConflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "head": exc.head}, status_code=409)

    @app.exception_handler(MissingBlobs)
    def on_missing(_request: Request, exc: MissingBlobs) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "missing": exc.hashes}, status_code=400)

    @app.exception_handler(InvalidInput)
    def on_invalid(_request: Request, exc: InvalidInput) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(UnknownVersion)
    def on_unknown(_request: Request, exc: UnknownVersion) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/slots")
    def list_slots(_device: str = Depends(device)) -> list[dict]:
        return [{"name": name, "head": head} for name, head in store.list_slots()]

    @app.get("/slots/{slot:path}/versions")
    def history(slot: str, _device: str = Depends(device)) -> list[dict]:
        return [v.to_dict(with_files=False) for v in store.history(slot)]

    @app.get("/slots/{slot:path}/versions/{ref}")
    def get_version(slot: str, ref: str, _device: str = Depends(device)) -> dict:
        if ref == "head":
            version = store.head(slot)
        elif ref.isdigit():
            version = store.version(slot, int(ref))
        else:
            version = None
        if version is None:
            raise HTTPException(status_code=404, detail="no such version")
        return version.to_dict()

    @app.post("/slots/{slot:path}/versions", status_code=201)
    def create_version(slot: str, body: CreateVersionBody, name: str = Depends(device)) -> dict:
        if body.label not in CLIENT_LABELS:
            raise HTTPException(status_code=400, detail=f"label not allowed: {body.label}")
        manifest = Manifest.of(FileEntry(**f.model_dump()) for f in body.files)
        return store.create_version(slot, body.base, manifest, name, body.label).to_dict()

    @app.post("/slots/{slot:path}/restore", status_code=201)
    def restore(slot: str, body: RestoreBody, name: str = Depends(device)) -> dict:
        return store.restore(slot, body.version, body.base, name).to_dict()

    @app.post("/slots/{slot:path}/keep-server", status_code=201)
    def keep_server(slot: str, body: KeepServerBody, name: str = Depends(device)) -> dict:
        lost = Manifest.of(FileEntry(**f.model_dump()) for f in body.files)
        return store.keep_server(slot, body.base, lost, name).to_dict()

    @app.post("/blobs/missing")
    def missing(body: MissingBody, _device: str = Depends(device)) -> dict:
        return {"missing": store.missing_blobs(body.hashes)}

    @app.put("/blobs/{sha256}", status_code=204)
    async def put_blob(sha256: str, request: Request, _device: str = Depends(device)) -> Response:
        store.put_blob(sha256, await request.body())
        return Response(status_code=204)

    @app.get("/blobs/{sha256}")
    def get_blob(sha256: str, _device: str = Depends(device)) -> FileResponse:
        path = store.blob_path(sha256)
        if path is None:
            raise HTTPException(status_code=404, detail="no such blob")
        return FileResponse(path, media_type="application/octet-stream")

    return app
