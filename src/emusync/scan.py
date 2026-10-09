from __future__ import annotations

import hashlib
import os
from pathlib import Path

from emusync.model import TMP_SUFFIX, FileEntry, Manifest

CHUNK_SIZE = 1 << 20


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def scan(root: Path) -> Manifest:
    if not root.is_dir():
        return Manifest.empty()
    resolved = root.resolve()
    entries = []
    for dirpath, _dirnames, filenames in os.walk(resolved, followlinks=True):
        for name in filenames:
            if name.endswith(TMP_SUFFIX):
                continue
            path = Path(dirpath) / name
            if not path.is_file():
                continue
            stat = path.stat()
            entries.append(
                FileEntry(
                    path=path.relative_to(resolved).as_posix(),
                    sha256=sha256_file(path),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
            )
    return Manifest.of(entries)
