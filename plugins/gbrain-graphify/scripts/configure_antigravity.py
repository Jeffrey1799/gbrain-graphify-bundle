#!/usr/bin/env python3
"""Backward-compatible Antigravity wrapper around the shared MCP helper."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from configure_mcp import (  # noqa: E402
    atomic_write,
    load_config,
    merge_servers as _merge_servers,
    server_matches,
    validate_servers as _validate_servers,
)
from configure_mcp import configure as _configure  # noqa: E402
from configure_mcp import desired_servers as _desired_servers  # noqa: E402


def default_config_path() -> Path:
    return Path.home() / ".gemini" / "antigravity" / "mcp_config.json"


def desired_servers(gbrain_command: str, graphify_command: str) -> dict[str, dict[str, object]]:
    return _desired_servers(
        gbrain_command,
        graphify_command,
        include_disabled=True,
    )


def merge_servers(
    config: dict[str, object],
    desired: dict[str, dict[str, object]],
    replace_conflicts: bool,
) -> tuple[dict[str, object], list[str], bool]:
    return _merge_servers(
        config,
        desired,
        replace_conflicts,
        root_key="mcpServers",
    )


def validate_servers(
    config: dict[str, object],
    desired: dict[str, dict[str, object]],
) -> list[str]:
    return _validate_servers(config, desired, root_key="mcpServers")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--gbrain-command", required=True)
    parser.add_argument("--graphify-command", required=True)
    parser.add_argument("--replace-conflicts", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    desired = desired_servers(args.gbrain_command, args.graphify_command)
    try:
        config = load_config(args.config)
        if args.validate_only:
            conflicts = validate_servers(config, desired)
            servers = config.get("mcpServers", {})
            present = [name for name in desired if isinstance(servers, dict) and name in servers]
            print(json.dumps({
                "platform": "antigravity",
                "config": str(args.config.resolve()),
                "schemaRoot": "mcpServers",
                "present": present,
                "conflicts": conflicts,
            }, ensure_ascii=True, indent=2))
            return 2 if conflicts else 0
        result = _configure(
            agent="antigravity",
            config_path=args.config,
            gbrain_command=args.gbrain_command,
            graphify_command=args.graphify_command,
            replace_conflicts=args.replace_conflicts,
            dry_run=args.dry_run,
            include_disabled=True,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            f"configuration is invalid and was not modified: {args.config}: {error}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 2 if result["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
