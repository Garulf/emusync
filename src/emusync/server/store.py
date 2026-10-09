from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterator

from emusync.model import FileEntry, Manifest, Version, is_safe_relative
from emusync.scan import sha256_bytes

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    name TEXT PRIMARY KEY,
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS slots (
    name TEXT PRIMARY KEY,
    head INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    slot TEXT NOT NULL,
    number INTEGER NOT NULL,
    device TEXT NOT NULL,
    created_at TEXT NOT NULL,
    label TEXT,
    PRIMARY KEY (slot, number)
);
CREATE TABLE IF NOT EXISTS version_files (
    slot TEXT NOT NULL,
    number INTEGER NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    PRIMARY KEY (slot, number, path)
);
"""


class StoreError(Exception):
    pass


class VersionConflict(StoreError):
    def __init__(self, head: int):
        super().__init__(f"base is stale, head is {head}")
        self.head = head


class MissingBlobs(StoreError):
    def __init__(self, hashes: list[str]):
        super().__init__(f"{len(hashes)} blobs not uploaded")
        self.hashes = hashes


class InvalidInput(StoreError):
    pass


class UnknownVersion(StoreError):
    pass


class DeviceExists(StoreError):
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _check_sha(sha256: str) -> None:
    if not SHA256_RE.match(sha256):
        raise InvalidInput(f"not a sha256: {sha256!r}")


def _check_slot(slot: str) -> None:
    if not is_safe_relative(slot):
        raise InvalidInput(f"bad slot name: {slot!r}")


def _check_manifest(manifest: Manifest) -> None:
    seen: set[str] = set()
    for entry in manifest.files:
        if not is_safe_relative(entry.path):
            raise InvalidInput(f"bad path: {entry.path!r}")
        if entry.path in seen:
            raise InvalidInput(f"duplicate path: {entry.path!r}")
        seen.add(entry.path)
        _check_sha(entry.sha256)


def _write_durably(target: Path, data: bytes) -> None:
    tmp = target.with_name(f"{target.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    directory_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


class Store:
    def __init__(
        self,
        data_dir: Path,
        keep_versions: int = 100,
        blob_grace_seconds: float = 3600.0,
        clock: Callable[[], float] = time.time,
    ):
        self.blobs_dir = data_dir / "blobs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.keep_versions = keep_versions
        self.blob_grace_seconds = blob_grace_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(
            data_dir / "emusync.db", check_same_thread=False, isolation_level=None
        )
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def add_device(self, name: str) -> str:
        if not name:
            raise InvalidInput("device name is empty")
        token = secrets.token_urlsafe(32)
        with self._transaction():
            row = self._db.execute(
                "SELECT revoked_at FROM devices WHERE name = ?", (name,)
            ).fetchone()
            if row is not None and row[0] is None:
                raise DeviceExists(name)
            self._db.execute(
                "INSERT OR REPLACE INTO devices VALUES (?, ?, ?, NULL)",
                (name, _hash_token(token), self._now()),
            )
        return token

    def list_devices(self) -> list[dict]:
        rows = self._read("SELECT name, created_at, revoked_at FROM devices ORDER BY name")
        return [{"name": n, "created_at": c, "revoked": r is not None} for n, c, r in rows]

    def revoke_device(self, name: str) -> bool:
        with self._transaction():
            cursor = self._db.execute(
                "UPDATE devices SET revoked_at = ? WHERE name = ? AND revoked_at IS NULL",
                (self._now(), name),
            )
        return cursor.rowcount > 0

    def authenticate(self, token: str) -> str | None:
        rows = self._read(
            "SELECT name FROM devices WHERE token_hash = ? AND revoked_at IS NULL",
            (_hash_token(token),),
        )
        return rows[0][0] if rows else None

    def list_slots(self) -> list[tuple[str, int]]:
        return [(n, h) for n, h in self._read("SELECT name, head FROM slots ORDER BY name")]

    def head(self, slot: str) -> Version | None:
        with self._lock:
            number = self._head_number(slot)
            return self._load_version(slot, number) if number else None

    def version(self, slot: str, number: int) -> Version | None:
        with self._lock:
            return self._load_version(slot, number)

    def history(self, slot: str) -> list[Version]:
        rows = self._read(
            "SELECT number, device, created_at, label FROM versions"
            " WHERE slot = ? ORDER BY number DESC",
            (slot,),
        )
        return [Version(n, d, c, label, Manifest.empty()) for n, d, c, label in rows]

    def missing_blobs(self, hashes: list[str]) -> list[str]:
        for sha in hashes:
            _check_sha(sha)
        return [sha for sha in dict.fromkeys(hashes) if not self._blob_file(sha).exists()]

    def put_blob(self, sha256: str, data: bytes) -> None:
        _check_sha(sha256)
        if sha256_bytes(data) != sha256:
            raise InvalidInput("blob content does not match its hash")
        target = self._blob_file(sha256)
        target.parent.mkdir(exist_ok=True)
        _write_durably(target, data)

    def blob_path(self, sha256: str) -> Path | None:
        _check_sha(sha256)
        path = self._blob_file(sha256)
        return path if path.exists() else None

    def create_version(
        self, slot: str, base: int, manifest: Manifest, device: str, label: str | None = None
    ) -> Version:
        _check_slot(slot)
        _check_manifest(manifest)
        with self._transaction():
            head = self._require_head(slot, base)
            self._require_blobs(manifest)
            number = self._insert_version(slot, head + 1, manifest, device, label)
        return self._finish(slot, number)

    def keep_server(self, slot: str, base: int, lost: Manifest, device: str) -> Version:
        _check_slot(slot)
        _check_manifest(lost)
        with self._transaction():
            head = self._require_head(slot, base)
            self._require_blobs(lost)
            kept = self._load_version(slot, base)
            if kept is None:
                raise UnknownVersion(f"{slot} has no version {base}")
            self._insert_version(slot, head + 1, lost, device, "conflict-lost")
            self._insert_version(slot, head + 2, kept.manifest, device, f"restore-of:{base}")
        return self._finish(slot, head + 2)

    def restore(self, slot: str, number: int, base: int, device: str) -> Version:
        _check_slot(slot)
        with self._transaction():
            head = self._require_head(slot, base)
            source = self._load_version(slot, number)
            if source is None:
                raise UnknownVersion(f"{slot} has no version {number}")
            new_number = self._insert_version(
                slot, head + 1, source.manifest, device, f"restore-of:{number}"
            )
        return self._finish(slot, new_number)

    def _finish(self, slot: str, number: int) -> Version:
        with self._lock:
            self._prune(slot, number)
            self._collect_garbage()
            return self._load_version(slot, number)

    def _require_blobs(self, manifest: Manifest) -> None:
        missing = sorted(h for h in manifest.hashes() if not self._blob_file(h).exists())
        if missing:
            raise MissingBlobs(missing)

    def _require_head(self, slot: str, base: int) -> int:
        head = self._head_number(slot)
        if base != head:
            raise VersionConflict(head)
        return head

    def _insert_version(
        self, slot: str, number: int, manifest: Manifest, device: str, label: str | None
    ) -> int:
        self._db.execute(
            "INSERT INTO versions VALUES (?, ?, ?, ?, ?)",
            (slot, number, device, self._now(), label),
        )
        self._db.executemany(
            "INSERT INTO version_files VALUES (?, ?, ?, ?, ?, ?)",
            [(slot, number, f.path, f.sha256, f.size, f.mtime) for f in manifest.files],
        )
        self._db.execute(
            "INSERT INTO slots VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET head = excluded.head",
            (slot, number),
        )
        return number

    def _head_number(self, slot: str) -> int:
        row = self._db.execute("SELECT head FROM slots WHERE name = ?", (slot,)).fetchone()
        return row[0] if row else 0

    def _load_version(self, slot: str, number: int) -> Version | None:
        row = self._db.execute(
            "SELECT device, created_at, label FROM versions WHERE slot = ? AND number = ?",
            (slot, number),
        ).fetchone()
        if row is None:
            return None
        files = self._db.execute(
            "SELECT path, sha256, size, mtime FROM version_files WHERE slot = ? AND number = ?",
            (slot, number),
        ).fetchall()
        manifest = Manifest.of(FileEntry(p, s, z, m) for p, s, z, m in files)
        return Version(number, row[0], row[1], row[2], manifest)

    def _prune(self, slot: str, head: int) -> None:
        cutoff = head - self.keep_versions
        if cutoff < 1:
            return
        self._db.execute("DELETE FROM versions WHERE slot = ? AND number <= ?", (slot, cutoff))
        self._db.execute(
            "DELETE FROM version_files WHERE slot = ? AND number <= ?", (slot, cutoff)
        )

    def _collect_garbage(self) -> None:
        referenced = {
            row[0] for row in self._db.execute("SELECT DISTINCT sha256 FROM version_files")
        }
        oldest_allowed = self._clock() - self.blob_grace_seconds
        for path in self.blobs_dir.glob("*/*"):
            if path.name in referenced:
                continue
            try:
                if path.stat().st_mtime < oldest_allowed:
                    path.unlink(missing_ok=True)
            except OSError:
                continue

    def _blob_file(self, sha256: str) -> Path:
        return self.blobs_dir / sha256[:2] / sha256

    def _now(self) -> str:
        return datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")

    def _read(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
