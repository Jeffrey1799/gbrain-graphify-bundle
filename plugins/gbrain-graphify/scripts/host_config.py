#!/usr/bin/env python3
"""Shared host metadata and user-level configuration path resolution."""

from __future__ import annotations

import argparse
import json
import os
import platform as platform_module
import shutil
from pathlib import Path
from typing import Callable, Mapping


SUPPORTED_HOSTS = (
    "codex",
    "claude",
    "antigravity",
    "workbuddy",
    "cursor",
    "vscode",
)

# Single source of truth for host-facing metadata.  Keep the values plain so
# shell wrappers and tests can consume the same registry without importing a
# platform-specific adapter.
HOST_REGISTRY = {
    "codex": {
        "aliases": [],
        "configPath": None,
        "schemaRoot": None,
        "adapter": ["graphify", "install", "--platform", "codex"],
        "doc": "https://developers.openai.com/codex/config-basic/#mcp-servers",
        "mode": "cli",
        "userSkillDir": None,
        "projectAdapter": None,
        "doctor": {"gbrainArgs": ["serve"], "graphifyArgs": []},
    },
    "claude": {
        "aliases": [],
        "configPath": None,
        "schemaRoot": None,
        "adapter": ["graphify", "install"],
        "doc": "https://modelcontextprotocol.io/quickstart/user#configuring-the-mcp-server",
        "mode": "cli",
        "userSkillDir": None,
        "projectAdapter": None,
        "doctor": {"gbrainArgs": ["serve"], "graphifyArgs": []},
    },
    "antigravity": {
        "aliases": ["google-antigravity"],
        "configPath": "~/.gemini/antigravity/mcp_config.json",
        "schemaRoot": "mcpServers",
        "adapter": ["graphify", "antigravity", "install"],
        "doc": "https://cloud.google.com/antigravity/docs/mcp",
        "mode": "file",
        "userSkillDir": ".gemini/config/skills",
        "projectAdapter": None,
        "doctor": {"gbrainArgs": ["serve"], "graphifyArgs": []},
    },
    "workbuddy": {
        "aliases": ["work-buddy"],
        "configPath": "~/.workbuddy/mcp.json",
        "schemaRoot": "mcpServers",
        "adapter": None,
        "doc": "https://www.codebuddy.cn/docs/ide/User-guide/MCP",
        "mode": "file",
        "userSkillDir": ".workbuddy/skills",
        "projectAdapter": None,
        "doctor": {"gbrainArgs": ["serve"], "graphifyArgs": []},
    },
    "cursor": {
        "aliases": [],
        "configPath": "~/.cursor/mcp.json",
        "schemaRoot": "mcpServers",
        "adapter": ["graphify", "cursor", "install"],
        "doc": "https://cursor.com/docs/mcp",
        "mode": "file",
        "userSkillDir": None,
        "projectAdapter": ["graphify", "cursor", "install"],
        "doctor": {"gbrainArgs": ["serve"], "graphifyArgs": []},
    },
    "vscode": {
        "aliases": ["vs-code", "visual-studio-code"],
        "configPath": None,
        "schemaRoot": "servers",
        "adapter": ["graphify", "vscode", "install"],
        "doc": "https://code.visualstudio.com/docs/agent-customization/mcp-servers",
        "mode": "file",
        "userSkillDir": ".copilot/skills",
        "projectAdapter": ["graphify", "vscode", "install"],
        "doctor": {"gbrainArgs": ["serve"], "graphifyArgs": []},
    },
}

ALIASES = {
    "vs-code": "vscode",
    "visual-studio-code": "vscode",
    "work-buddy": "workbuddy",
    "google-antigravity": "antigravity",
}
for _host, _metadata in HOST_REGISTRY.items():
    for _alias in _metadata["aliases"]:
        ALIASES.setdefault(_alias, _host)

PLATFORM_MCP_DOCS = {host: metadata["doc"] for host, metadata in HOST_REGISTRY.items()}
SCHEMA_ROOTS = {
    host: metadata["schemaRoot"]
    for host, metadata in HOST_REGISTRY.items()
    if metadata["schemaRoot"]
}
USER_SKILL_DIRS = {
    host: metadata["userSkillDir"]
    for host, metadata in HOST_REGISTRY.items()
    if metadata["userSkillDir"]
}


def canonical_agent(value: str) -> str:
    normalized = value.strip().lower()
    normalized = ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_HOSTS:
        raise ValueError(
            f"unsupported agent '{value}'. Choose from: {', '.join(SUPPORTED_HOSTS)}"
        )
    return normalized


def schema_root(agent: str) -> str:
    return SCHEMA_ROOTS[canonical_agent(agent)]


def default_config_path(
    agent: str,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    system: str | None = None,
) -> Path | None:
    """Return a host's user MCP path; CLI-managed hosts return None."""

    host = canonical_agent(agent)
    env = dict(os.environ if environ is None else environ)
    home_path = Path(home) if home is not None else Path.home()
    if host in {"codex", "claude"}:
        return None
    if host == "antigravity":
        return home_path / ".gemini" / "antigravity" / "mcp_config.json"
    if host == "workbuddy":
        return home_path / ".workbuddy" / "mcp.json"
    if host == "cursor":
        return home_path / ".cursor" / "mcp.json"

    portable = env.get("VSCODE_PORTABLE")
    if portable:
        return Path(portable) / "User" / "mcp.json"
    system_name = system or platform_module.system()
    if system_name == "Windows":
        app_data = env.get("APPDATA") or str(home_path / "AppData" / "Roaming")
        return Path(app_data) / "Code" / "User" / "mcp.json"
    if system_name == "Darwin":
        return home_path / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    xdg = env.get("XDG_CONFIG_HOME") or str(home_path / ".config")
    return Path(xdg) / "Code" / "User" / "mcp.json"


def user_skill_path(agent: str, *, home: Path | None = None) -> Path | None:
    host = canonical_agent(agent)
    relative = USER_SKILL_DIRS.get(host)
    if relative is None:
        return None
    root = Path(home) if home is not None else Path.home()
    return root / relative


def project_adapter(agent: str) -> list[str] | None:
    host = canonical_agent(agent)
    adapter = HOST_REGISTRY[host]["projectAdapter"]
    return list(adapter) if isinstance(adapter, list) else None


def detect_candidates(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    command_exists: Callable[[str], bool] | None = None,
) -> list[str]:
    env = dict(os.environ if environ is None else environ)
    home_path = Path(home) if home is not None else Path.home()
    if command_exists is None:
        command_exists = lambda name: shutil.which(name, path=env.get("PATH")) is not None

    marker = env.get("GBRAIN_AGENT", "").strip()
    if marker:
        return [canonical_agent(marker)]

    candidates: list[str] = []
    signals = {
        "codex": command_exists("codex") or (home_path / ".codex").exists(),
        "claude": command_exists("claude") or (home_path / ".claude").exists(),
        "antigravity": (home_path / ".gemini" / "antigravity").exists(),
        "workbuddy": command_exists("workbuddy") or (home_path / ".workbuddy").exists(),
        "cursor": command_exists("cursor") or (home_path / ".cursor").exists(),
        "vscode": command_exists("code")
        or command_exists("code-insiders")
        or default_config_path("vscode", home=home_path, environ=env).exists(),
    }
    candidates.extend(host for host in SUPPORTED_HOSTS if signals[host])
    return candidates


def resolve_agent(
    requested: str,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    command_exists: Callable[[str], bool] | None = None,
) -> str:
    value = requested.strip().lower()
    if value and value != "auto":
        return canonical_agent(value)
    candidates = detect_candidates(
        home=home, environ=environ, command_exists=command_exists
    )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            "could not detect a supported agent; rerun with --agent "
            "codex|claude|antigravity|workbuddy|cursor|vscode"
        )
    raise ValueError(
        "multiple supported agents detected ("
        + ", ".join(candidates)
        + "); rerun with an explicit --agent"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detect", action="store_true")
    parser.add_argument("--agent", default="auto")
    parser.add_argument("--config-path", action="store_true")
    args = parser.parse_args()
    try:
        if args.detect:
            print(json.dumps(detect_candidates(), ensure_ascii=True))
            return 0
        agent = resolve_agent(args.agent)
        if args.config_path:
            path = default_config_path(agent)
            print(str(path) if path else "")
        else:
            print(agent)
        return 0
    except ValueError as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
