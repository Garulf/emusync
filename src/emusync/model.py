from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

TMP_SUFFIX = ".emusync-tmp"


def is_safe_relative(path: str) -> bool:
    if not path or "\\" in path:
        return False
    pure = PurePosixPath(path)
    return not pure.is_absolute() and ".." not in pure.parts and str(pure) == path and path != "."


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size: int
    mtime: float

    def to_dict(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "size": self.size, "mtime": self.mtime}

    @classmethod
    def from_dict(cls, d: dict) -> FileEntry:
        return cls(path=d["path"], sha256=d["sha256"], size=int(d["size"]), mtime=float(d["mtime"]))


@dataclass(frozen=True)
class Manifest:
    files: tuple[FileEntry, ...]

    @classmethod
    def of(cls, entries: Iterable[FileEntry]) -> Manifest:
        return cls(tuple(sorted(entries, key=lambda e: e.path)))

    @classmethod
    def empty(cls) -> Manifest:
        return cls(())

    @classmethod
    def from_list(cls, items: Iterable[dict]) -> Manifest:
        return cls.of(FileEntry.from_dict(d) for d in items)

    def to_list(self) -> list[dict]:
        return [f.to_dict() for f in self.files]

    def is_empty(self) -> bool:
        return not self.files

    def same_content(self, other: Manifest) -> bool:
        return self._content() == other._content()

    def by_path(self) -> dict[str, FileEntry]:
        return {f.path: f for f in self.files}

    def hashes(self) -> set[str]:
        return {f.sha256 for f in self.files}

    def latest_mtime(self) -> float | None:
        return max((f.mtime for f in self.files), default=None)

    def _content(self) -> frozenset[tuple[str, str]]:
        return frozenset((f.path, f.sha256) for f in self.files)


@dataclass(frozen=True)
class Version:
    number: int
    device: str
    created_at: str
    label: str | None
    manifest: Manifest

    def to_dict(self, with_files: bool = True) -> dict:
        d = {
            "number": self.number,
            "device": self.device,
            "created_at": self.created_at,
            "label": self.label,
        }
        if with_files:
            d["files"] = self.manifest.to_list()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Version:
        return cls(
            number=int(d["number"]),
            device=d["device"],
            created_at=d["created_at"],
            label=d.get("label"),
            manifest=Manifest.from_list(d.get("files", [])),
        )
