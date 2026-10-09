from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from emusync.model import FileEntry, Manifest, Version


class Action(StrEnum):
    NOTHING = "nothing"
    PUSH = "push"
    PULL = "pull"
    ADOPT = "adopt"
    CONFLICT = "conflict"
    SKIP_EMPTY = "skip-empty"


@dataclass(frozen=True)
class Base:
    version: int
    manifest: Manifest


def decide(local: Manifest, base: Base | None, head: Version | None) -> Action:
    if base is None:
        return _first_sync(local, head)
    if head is None:
        return Action.NOTHING if local.is_empty() else Action.PUSH

    local_changed = not local.same_content(base.manifest)
    if local_changed and local.is_empty() and not base.manifest.is_empty():
        return Action.SKIP_EMPTY
    if _server_history_diverged(base, head):
        return Action.ADOPT if local.same_content(head.manifest) else Action.CONFLICT

    remote_changed = head.number != base.version
    if remote_changed and head.manifest.is_empty() and not local.is_empty():
        return Action.CONFLICT
    if not local_changed and not remote_changed:
        return Action.NOTHING
    if local_changed and not remote_changed:
        return Action.PUSH
    if remote_changed and not local_changed:
        return Action.PULL
    return _reconcile(local, base.manifest, head)


def _server_history_diverged(base: Base, head: Version) -> bool:
    if head.number < base.version:
        return True
    return head.number == base.version and not head.manifest.same_content(base.manifest)


def _first_sync(local: Manifest, head: Version | None) -> Action:
    if head is None:
        return Action.NOTHING if local.is_empty() else Action.PUSH
    if local.is_empty():
        return Action.PULL
    return _reconcile(local, Manifest.empty(), head)


def _reconcile(local: Manifest, base: Manifest, head: Version) -> Action:
    if local.same_content(head.manifest):
        return Action.ADOPT
    if _local_changes_match_head(local, base, head.manifest):
        return Action.PULL
    return Action.CONFLICT


def _local_changes_match_head(local: Manifest, base: Manifest, head: Manifest) -> bool:
    local_files, base_files, head_files = local.by_path(), base.by_path(), head.by_path()
    changed = {
        path
        for path in local_files.keys() | base_files.keys()
        if _sha(local_files, path) != _sha(base_files, path)
    }
    return all(_sha(local_files, path) == _sha(head_files, path) for path in changed)


def _sha(files: dict[str, FileEntry], path: str) -> str | None:
    entry = files.get(path)
    return entry.sha256 if entry else None
