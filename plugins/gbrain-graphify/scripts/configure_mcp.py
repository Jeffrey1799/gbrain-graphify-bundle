#!/usr/bin/env python3
"""Safe, schema-aware MCP configuration merge for file-based hosts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from host_config import default_config_path, schema_root


def desired_servers(
    gbrain_command: str,
    graphify_command: str,
    *,
    include_disabled: bool = False,
) -> dict[str, dict[str, object]]:
    if not gbrain_command.strip():
        raise ValueError("gbrain command must be non-empty")
    if not graphify_command.strip():
        raise ValueError("graphify command must be non-empty")
    gbrain: dict[str, object] = {
        "type": "stdio",
        "command": gbrain_command,
        "args": ["serve"],
    }
    graphify: dict[str, object] = {
        "type": "stdio",
        "command": graphify_command,
        "args": [],
    }
    if include_disabled:
        gbrain["disabled"] = False
        graphify["disabled"] = False
    return {"gbrain": gbrain, "graphify": graphify}


def _normalized_command(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return os.path.normcase(os.path.abspath(os.path.expanduser(value)))


def server_matches(current: object, expected: dict[str, object]) -> bool:
    if not isinstance(current, dict):
        return False
    return (
        current.get("type") == "stdio"
        and _normalized_command(current.get("command"))
        == _normalized_command(expected.get("command"))
        and current.get("args", []) == expected.get("args", [])
        and current.get("disabled") is not True
    )


def load_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"configuration root must be an object: {path}")
    return data


def _servers(config: dict[str, object], root_key: str) -> dict[str, object]:
    raw = config.get(root_key, {})
    if not isinstance(raw, dict):
        raise ValueError(f"{root_key} must be an object")
    return dict(raw)


def merge_servers(
    config: dict[str, object],
    desired: dict[str, dict[str, object]],
    replace_conflicts: bool,
    *,
    root_key: str = "mcpServers",
) -> tuple[dict[str, object], list[str], bool]:
    merged = dict(config)
    servers = _servers(merged, root_key)
    conflicts: list[str] = []
    changed = False

    for name, value in desired.items():
        if name not in servers:
            servers[name] = value
            changed = True
            continue
        current = servers[name]
        if server_matches(current, value):
            continue
        if not replace_conflicts:
            conflicts.append(name)
            continue
        servers[name] = value
        changed = True

    merged[root_key] = servers
    return merged, conflicts, changed


def validate_servers(
    config: dict[str, object],
    desired: dict[str, dict[str, object]],
    *,
    root_key: str = "mcpServers",
) -> list[str]:
    servers = _servers(config, root_key)
    return [
        name
        for name, expected in desired.items()
        if name in servers and not server_matches(servers[name], expected)
    ]


def atomic_write(path: Path, data: dict[str, object]) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = path.with_name(f"{path.name}.{stamp}.bak")
        shutil.copy2(path, backup)

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=True, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return backup


def configure(
    *,
    agent: str,
    config_path: Path,
    gbrain_command: str,
    graphify_command: str,
    replace_conflicts: bool = False,
    dry_run: bool = False,
    include_disabled: bool = False,
) -> dict[str, Any]:
    root_key = schema_root(agent)
    desired = desired_servers(
        gbrain_command,
        graphify_command,
        include_disabled=include_disabled,
    )
    config = load_config(config_path)
    merged, conflicts, changed = merge_servers(
        config, desired, replace_conflicts, root_key=root_key
    )
    result: dict[str, Any] = {
        "platform": agent,
        "config": str(config_path.resolve()),
        "schemaRoot": root_key,
        "changed": changed,
        "dryRun": dry_run,
        "conflicts": conflicts,
        "backup": None,
    }
    if conflicts:
        return result
    if changed and not dry_run:
        backup = atomic_write(config_path, merged)
        result["backup"] = str(backup) if backup else None
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True, choices=("antigravity", "workbuddy", "cursor", "vscode"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--gbrain-command", required=True)
    parser.add_argument("--graphify-command", required=True)
    parser.add_argument("--replace-conflicts", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-disabled", action="store_true")
    args = parser.parse_args()
    path = args.config or default_config_path(args.platform)
    if path is None:
        parser.error(f"{args.platform} uses a CLI-managed MCP configuration")
    try:
        desired = desired_servers(
            args.gbrain_command,
            args.graphify_command,
            include_disabled=args.include_disabled,
        )
        config = load_config(path)
        root_key = schema_root(args.platform)
        if args.validate_only:
            servers = _servers(config, root_key)
            conflicts = validate_servers(config, desired, root_key=root_key)
            present = [name for name in desired if name in servers]
            print(json.dumps({
                "platform": args.platform,
                "config": str(path.resolve()),
                "schemaRoot": root_key,
                "present": present,
                "conflicts": conflicts,
            }, ensure_ascii=True, indent=2))
            return 2 if conflicts else 0
        result = configure(
            agent=args.platform,
            config_path=path,
            gbrain_command=args.gbrain_command,
            graphify_command=args.graphify_command,
            replace_conflicts=args.replace_conflicts,
            dry_run=args.dry_run,
            include_disabled=args.include_disabled,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            f"configuration is invalid and was not modified: {path}: {error}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 2 if result["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
