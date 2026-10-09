from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from emusync.client.api import Api, Offline, PushRejected
from emusync.client.state import State
from emusync.decide import Action, Base, decide
from emusync.model import TMP_SUFFIX, FileEntry, Manifest, Version, is_safe_relative
from emusync.scan import scan, sha256_bytes

MAX_CONFLICT_ROUNDS = 3


class Outcome(StrEnum):
    IN_SYNC = "in sync"
    PUSHED = "pushed"
    PULLED = "pulled"
    ADOPTED = "already matched server"
    KEPT_LOCAL = "conflict: kept this device"
    KEPT_SERVER = "conflict: kept server"
    SKIPPED_CONFLICT = "conflict: skipped"
    SKIPPED_EMPTY = "skipped: folder is empty"
    OFFLINE = "offline"


SUCCESSFUL = frozenset(
    {
        Outcome.IN_SYNC,
        Outcome.PUSHED,
        Outcome.PULLED,
        Outcome.ADOPTED,
        Outcome.KEPT_LOCAL,
        Outcome.KEPT_SERVER,
    }
)


class Choice(StrEnum):
    LOCAL = "local"
    SERVER = "server"


class Prompter(Protocol):
    def choose(self, slot: str, local: Manifest, server: Version) -> Choice | None: ...


class SyncError(Exception):
    pass


class RestoreAborted(Exception):
    def __init__(self, outcome: Outcome):
        super().__init__(f"local copy could not be synced first: {outcome}")
        self.outcome = outcome


class Syncer:
    def __init__(self, api: Api, state: State, prompter: Prompter):
        self.api = api
        self.state = state
        self.prompter = prompter

    def plan(self, slot: str, root: Path) -> Action:
        return decide(scan(root), self.state.base(slot), self.api.head(slot))

    def sync(self, slot: str, root: Path) -> Outcome:
        try:
            return self._sync(slot, root)
        except Offline:
            return Outcome.OFFLINE

    def restore(self, slot: str, root: Path, number: int) -> Outcome:
        outcome = self.sync(slot, root)
        if outcome not in SUCCESSFUL:
            raise RestoreAborted(outcome)
        head = self.api.head(slot)
        restored = self.api.restore(slot, number, base=head.number if head else 0)
        self._pull(slot, root, scan(root), restored)
        return Outcome.PULLED

    def _sync(self, slot: str, root: Path) -> Outcome:
        local = scan(root)
        head = self.api.head(slot)
        action = decide(local, self.state.base(slot), head)
        if action is Action.NOTHING:
            return Outcome.IN_SYNC
        if action is Action.SKIP_EMPTY:
            return Outcome.SKIPPED_EMPTY
        if action is Action.ADOPT:
            return self._adopt(slot, head)
        if action is Action.PULL:
            self._pull(slot, root, local, head)
            return Outcome.PULLED
        if action is Action.PUSH:
            try:
                self._push(slot, root, local, base=head.number if head else 0)
            except PushRejected:
                return self._after_push_race(slot, root, local)
            return Outcome.PUSHED
        return self._resolve(slot, root, local, head)

    def _after_push_race(self, slot: str, root: Path, local: Manifest) -> Outcome:
        head = self.api.head(slot)
        if local.same_content(head.manifest):
            return self._adopt(slot, head)
        return self._resolve(slot, root, local, head)

    def _resolve(self, slot: str, root: Path, local: Manifest, head: Version) -> Outcome:
        for _round in range(MAX_CONFLICT_ROUNDS):
            choice = self.prompter.choose(slot, local, head)
            if choice is None:
                return Outcome.SKIPPED_CONFLICT
            try:
                return self._apply_choice(slot, root, local, head, choice)
            except PushRejected:
                head = self.api.head(slot)
        return Outcome.SKIPPED_CONFLICT

    def _apply_choice(
        self, slot: str, root: Path, local: Manifest, head: Version, choice: Choice
    ) -> Outcome:
        if choice is Choice.LOCAL:
            self._push(slot, root, local, base=head.number)
            return Outcome.KEPT_LOCAL
        self._upload_missing(root, local)
        restored = self.api.keep_server(slot, head.number, local)
        self._pull(slot, root, local, restored)
        return Outcome.KEPT_SERVER

    def _adopt(self, slot: str, head: Version) -> Outcome:
        self.state.set_base(slot, Base(head.number, head.manifest))
        return Outcome.ADOPTED

    def _push(
        self, slot: str, root: Path, local: Manifest, base: int, label: str | None = None
    ) -> Version:
        self._upload_missing(root, local)
        version = self.api.create_version(slot, base, local, label)
        self.state.set_base(slot, Base(version.number, local))
        return version

    def _upload_missing(self, root: Path, local: Manifest) -> None:
        by_hash = {entry.sha256: entry for entry in local.files}
        for sha in self.api.missing(sorted(by_hash)):
            data = (root / by_hash[sha].path).read_bytes()
            if sha256_bytes(data) != sha:
                raise SyncError(f"{by_hash[sha].path} changed during sync, try again")
            self.api.upload(sha, data)

    def _pull(self, slot: str, root: Path, local: Manifest, head: Version) -> None:
        for entry in head.manifest.files:
            if not is_safe_relative(entry.path):
                raise SyncError(f"server sent an unsafe path: {entry.path!r}")
        root.mkdir(parents=True, exist_ok=True)
        current = local.by_path()
        touched: set[Path] = set()
        for entry in head.manifest.files:
            have = current.get(entry.path)
            if have is None or have.sha256 != entry.sha256:
                self._write(root, entry)
                touched.update(_directories_within(root, entry.path))
        wanted = {entry.path for entry in head.manifest.files}
        for path in current.keys() - wanted:
            (root / path).unlink(missing_ok=True)
            touched.update(_directories_within(root, path))
        _fsync_directories(touched)
        self.state.set_base(slot, Base(head.number, head.manifest))

    def _write(self, root: Path, entry: FileEntry) -> None:
        data = self.api.download(entry.sha256)
        if sha256_bytes(data) != entry.sha256:
            raise SyncError(f"download of {entry.path} is corrupt")
        target = root / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + TMP_SUFFIX)
        _write_synced(tmp, data)
        os.utime(tmp, (entry.mtime, entry.mtime))
        os.replace(tmp, target)


def _write_synced(path: Path, data: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _directories_within(root: Path, relative_file: str) -> list[Path]:
    return [root / parent for parent in Path(relative_file).parents]


def _fsync_directories(directories: set[Path]) -> None:
    for directory in sorted(directories):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
