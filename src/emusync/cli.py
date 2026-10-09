from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from emusync.client.api import Api, ApiError, Offline, Unauthorized
from emusync.client.config import (
    Config,
    ConfigError,
    config_path,
    discover_slots,
    slots_for_emulator,
    state_path,
    write_login,
)
from emusync.client.prompt import notify, pick_prompter
from emusync.client.state import State
from emusync.client.sync import SUCCESSFUL, Outcome, RestoreAborted, SyncError, Syncer
from emusync.decide import Action
from emusync.server.store import DeviceExists, Store

STATUS_TEXT = {
    Action.NOTHING: "in sync",
    Action.PUSH: "local changes",
    Action.PULL: "server ahead",
    Action.ADOPT: "matches server",
    Action.CONFLICT: "conflict",
    Action.SKIP_EMPTY: "folder empty, will not push",
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ConfigError, ApiError, SyncError, RestoreAborted, OSError) as err:
        print(f"emusync: {err}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="emusync", description="Sync EmuDeck saves.")
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser("login", help="save server URL and device token")
    login.add_argument("server_url")
    login.add_argument("token")
    login.set_defaults(handler=cmd_login)

    status = commands.add_parser("status", help="show what a sync would do")
    status.set_defaults(handler=cmd_status)

    sync = commands.add_parser("sync", help="sync slots with the server")
    sync.add_argument("slots", nargs="*")
    sync.add_argument("--emulator")
    sync.set_defaults(handler=cmd_sync)

    history = commands.add_parser("history", help="list versions of a slot")
    history.add_argument("slot")
    history.set_defaults(handler=cmd_history)

    restore = commands.add_parser("restore", help="restore a slot to an old version")
    restore.add_argument("slot")
    restore.add_argument("version", type=int)
    restore.set_defaults(handler=cmd_restore)

    run = commands.add_parser("run", help="sync, run a command, sync again")
    run.add_argument("emulator")
    run.add_argument("cmd", nargs=argparse.REMAINDER)
    run.set_defaults(handler=cmd_run)

    serve = commands.add_parser("serve", help="run the sync server")
    _add_data_arg(serve)
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--keep", type=int, default=100, help="versions kept per slot")
    serve.set_defaults(handler=cmd_serve)

    admin = commands.add_parser("admin", help="server administration")
    device = admin.add_subparsers(dest="admin_command", required=True).add_parser("device")
    device_commands = device.add_subparsers(dest="device_command", required=True)
    add = device_commands.add_parser("add")
    add.add_argument("name")
    _add_data_arg(add)
    add.set_defaults(handler=cmd_device_add)
    listing = device_commands.add_parser("list")
    _add_data_arg(listing)
    listing.set_defaults(handler=cmd_device_list)
    revoke = device_commands.add_parser("revoke")
    revoke.add_argument("name")
    _add_data_arg(revoke)
    revoke.set_defaults(handler=cmd_device_revoke)

    return parser


def _add_data_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data", default=os.environ.get("EMUSYNC_DATA", "/data"))


def cmd_login(args: argparse.Namespace) -> int:
    write_login(config_path(), args.server_url, args.token)
    try:
        Api.connect(args.server_url, args.token).check()
    except Offline as err:
        print(f"Saved, but the server is unreachable: {err}", file=sys.stderr)
        return 1
    print(f"Connected to {args.server_url}")
    return 0


def _syncer(config: Config) -> Syncer:
    api = Api.connect(config.server_url, config.token)
    return Syncer(api, State(state_path()), pick_prompter())


def _select(config: Config, names: list[str], emulator: str | None) -> dict[str, Path]:
    slots = discover_slots(config)
    if emulator:
        slots = slots_for_emulator(slots, emulator)
    if not names:
        return slots
    unknown = [name for name in names if name not in slots]
    if unknown:
        raise ConfigError(f"unknown slot: {', '.join(unknown)}")
    return {name: slots[name] for name in names}


def cmd_status(args: argparse.Namespace) -> int:
    config = Config.load(config_path())
    syncer = _syncer(config)
    for name, root in _select(config, [], None).items():
        try:
            action = syncer.plan(name, root)
        except Offline:
            print("server unreachable")
            return 0
        print(f"{name:<32} {STATUS_TEXT[action]}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    config = Config.load(config_path())
    return _sync_slots(_syncer(config), _select(config, args.slots, args.emulator))


def _sync_slots(syncer: Syncer, slots: dict[str, Path]) -> int:
    exit_code = 0
    for name, root in slots.items():
        try:
            outcome = syncer.sync(name, root)
        except (SyncError, ApiError, OSError) as err:
            notify(f"{name}: {err}")
            exit_code = 1
            if isinstance(err, Unauthorized):
                break
            continue
        print(f"{name}: {outcome}")
        if outcome is Outcome.OFFLINE:
            notify("server unreachable, playing with local saves")
            break
        if outcome not in SUCCESSFUL:
            notify(f"{name}: {outcome}")
    return exit_code


def cmd_history(args: argparse.Namespace) -> int:
    config = Config.load(config_path())
    for version in _syncer(config).api.history(args.slot):
        when = datetime.fromisoformat(version.created_at).astimezone()
        print(f"{version.number:>5}  {when:%Y-%m-%d %H:%M}  {version.device:<16} {version.label or ''}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    config = Config.load(config_path())
    root = _select(config, [args.slot], None)[args.slot]
    _syncer(config).restore(args.slot, root, args.version)
    print(f"Restored {args.slot} to version {args.version}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    command = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not command:
        raise ConfigError("nothing to run, usage: emusync run EMULATOR -- COMMAND...")
    config = Config.load(config_path())
    syncer = _syncer(config)
    slots = _select(config, [], args.emulator)
    _sync_slots(syncer, slots)
    exit_code = subprocess.call(command)
    _sync_slots(syncer, slots)
    return exit_code


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn

        from emusync.server.app import create_app
    except ImportError:
        print("emusync: server dependencies missing, install emusync[server]", file=sys.stderr)
        return 1
    store = Store(Path(args.data), keep_versions=args.keep)
    uvicorn.run(create_app(store), host=args.host, port=args.port)
    return 0


def cmd_device_add(args: argparse.Namespace) -> int:
    store = Store(Path(args.data))
    try:
        token = store.add_device(args.name)
    except DeviceExists:
        print(f"emusync: device {args.name} already exists", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(f"Token for {args.name} (shown once):")
    print(token)
    return 0


def cmd_device_list(args: argparse.Namespace) -> int:
    store = Store(Path(args.data))
    for device in store.list_devices():
        state = "revoked" if device["revoked"] else "active"
        print(f"{device['name']:<20} {state:<8} {device['created_at']}")
    store.close()
    return 0


def cmd_device_revoke(args: argparse.Namespace) -> int:
    store = Store(Path(args.data))
    revoked = store.revoke_device(args.name)
    store.close()
    if not revoked:
        print(f"emusync: no active device named {args.name}", file=sys.stderr)
        return 1
    return 0
