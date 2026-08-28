#!/usr/bin/env python3
"""Read-only health checks for the GBrain + Graphify integration."""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from host_config import (  # noqa: E402
    PLATFORM_MCP_DOCS,
    SUPPORTED_HOSTS,
    default_config_path,
    schema_root,
    user_skill_path,
)

# Official MCP configuration documentation URLs per platform.
# Agents should consult these docs when mcp.json entries are rejected.
def platform_doc_url(agent: str) -> str | None:
    """Return the official MCP config doc URL for a given platform, if known."""
    return PLATFORM_MCP_DOCS.get(agent.lower())


def fix_bom(path: Path, dry_run: bool = False) -> dict[str, object]:
    """Strip UTF-8 BOM from a file if present. Returns a report dict."""
    if not path.is_file():
        return {"ok": False, "error": "file not found", "path": str(path)}
    raw = path.read_bytes()
    if not raw.startswith(b'\xef\xbb\xbf'):
        return {"ok": True, "fixed": False, "path": str(path), "detail": "no BOM found"}
    if dry_run:
        return {"ok": True, "fixed": False, "path": str(path), "detail": "BOM would be stripped (dry-run)"}
    # Strip BOM: write everything after the 3-byte BOM marker
    path.write_bytes(raw[3:])
    return {"ok": True, "fixed": True, "path": str(path), "detail": "BOM stripped"}


def resolve_process_command(command: list[str]) -> list[str]:
    executable = shutil.which(command[0])
    resolved = [executable or command[0], *command[1:]]
    if executable and Path(executable).suffix.lower() == ".ps1":
        powershell = shutil.which("powershell.exe") or "powershell.exe"
        resolved = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            executable,
            *command[1:],
        ]
    elif executable and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        resolved = [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", executable, *command[1:]]
    return resolved


def run(command: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        resolve_process_command(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def check_command(name: str) -> dict[str, object]:
    path = shutil.which(name)
    return {"ok": path is not None, "path": path}


def normalize_command(path: str) -> str:
    if not path:
        return ""
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def command_leaf(path: str) -> str:
    return Path(path).stem.lower() if path else ""


def validate_stdio_entry(
    entry: object,
    name: str,
    expected_command: str | None = None,
    require_type: bool = True,
) -> dict[str, object]:
    if not isinstance(entry, dict):
        return {"ok": False, "error": "entry not found or not an object"}

    entry_type = entry.get("type")
    if require_type and entry_type != "stdio":
        return {"ok": False, "error": f'expected type="stdio", got {entry_type!r}'}
    if not require_type and entry_type not in (None, "stdio"):
        return {"ok": False, "error": f'expected stdio entry, got type={entry_type!r}'}
    if entry.get("disabled") is True:
        return {"ok": False, "error": "entry is disabled"}

    command = str(entry.get("command", ""))
    args = entry.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        return {"ok": False, "error": "args must be an array of strings"}
    expected_args = ["serve"] if name == "gbrain" else []
    expected_leaf = "gbrain" if name == "gbrain" else "graphify-mcp"
    if expected_command:
        command_ok = normalize_command(command) == normalize_command(expected_command)
    else:
        command_ok = command_leaf(command) == expected_leaf
    if not command_ok:
        return {"ok": False, "error": f"unexpected command: {command}"}
    if args != expected_args:
        return {"ok": False, "error": f"unexpected args: {args}", "expectedArgs": expected_args}
    return {
        "ok": True,
        "type": "stdio",
        "transport": "stdio",
        "command": command,
        "args": args,
    }


def parse_json_output(output: str) -> object | None:
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        for line in reversed(output.splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def gbrain_health() -> dict[str, object]:
    if not shutil.which("gbrain"):
        return {"ok": False, "error": "gbrain command not found"}
    try:
        result = run(["gbrain", "doctor", "--json"], timeout=60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "gbrain doctor timed out"}
    payload = parse_json_output(result.stdout)
    checks = payload.get("checks") if isinstance(payload, dict) else None
    connection = next(
        (
            check
            for check in checks
            if isinstance(check, dict) and check.get("name") == "connection"
        ),
        None,
    ) if isinstance(checks, list) else None
    schema_ok = isinstance(payload, dict) and payload.get("schema_version") == 2
    status_ok = isinstance(payload, dict) and payload.get("status") in {"healthy", "warnings"}
    connection_ok = isinstance(connection, dict) and connection.get("status") == "ok"
    ok = result.returncode == 0 and schema_ok and status_ok and connection_ok
    return {
        "ok": ok,
        "returncode": result.returncode,
        "report": payload,
        "schemaOk": schema_ok,
        "statusOk": status_ok,
        "connectionOk": connection_ok,
        "error": None if ok else (
            result.stderr.strip()
            or ("gbrain doctor did not report a healthy database connection" if isinstance(payload, dict)
                else result.stdout.strip() or "invalid JSON output")
        ),
    }


def mcp_handshake(command: str, args: list[str], timeout: int = 15) -> dict[str, object]:
    resolved = resolve_process_command([command, *args])
    messages: queue.Queue[object] = queue.Queue()
    stderr_lines: list[str] = []
    process: subprocess.Popen[str] | None = None

    try:
        process = subprocess.Popen(
            resolved,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None

        def read_stdout() -> None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue

        def read_stderr() -> None:
            stderr_lines.extend(line.rstrip() for line in process.stderr)

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()

        def send(payload: dict[str, object]) -> None:
            process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            process.stdin.flush()

        def wait_for(response_id: int) -> dict[str, object]:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                returncode = process.poll()
                if returncode is not None:
                    raise RuntimeError(f"MCP server exited with code {returncode}")
                remaining = max(0.05, deadline - time.monotonic())
                try:
                    candidate = messages.get(timeout=min(0.1, remaining))
                except queue.Empty:
                    continue
                if (
                    isinstance(candidate, dict)
                    and candidate.get("jsonrpc") == "2.0"
                    and candidate.get("id") == response_id
                ):
                    return candidate
            raise TimeoutError(f"MCP response {response_id} timed out")

        send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "gbrain-graphify-doctor", "version": "1.0.3"},
            },
        })
        initialized = wait_for(1)
        if initialized.get("jsonrpc") != "2.0":
            return {"ok": False, "error": "initialize returned an invalid JSON-RPC envelope"}
        if "error" in initialized:
            return {"ok": False, "error": initialized["error"]}
        initialize_result = initialized.get("result")
        if not isinstance(initialize_result, dict) or not isinstance(
            initialize_result.get("protocolVersion"), str
        ):
            return {"ok": False, "error": "initialize returned an invalid result"}
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_response = wait_for(2)
        if tools_response.get("jsonrpc") != "2.0":
            return {"ok": False, "error": "tools/list returned an invalid JSON-RPC envelope"}
        if "error" in tools_response:
            return {"ok": False, "error": tools_response["error"]}
        tools_result = tools_response.get("result")
        if not isinstance(tools_result, dict):
            return {"ok": False, "error": "tools/list returned an invalid result"}
        tools = tools_result.get("tools", [])
        return {
            "ok": isinstance(tools, list) and len(tools) > 0,
            "toolCount": len(tools) if isinstance(tools, list) else 0,
            "protocolVersion": initialize_result["protocolVersion"],
            "error": None if isinstance(tools, list) and tools else "tools/list returned no tools",
        }
    except (OSError, RuntimeError, TimeoutError) as error:
        return {"ok": False, "error": str(error), "stderr": "\n".join(stderr_lines[-20:])}
    finally:
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()


def gbrain_version() -> str | None:
    if not shutil.which("gbrain"):
        return None
    result = run(["gbrain", "--help"])
    match = re.search(r"^gbrain\s+([0-9]+(?:\.[0-9]+)+)", result.stdout, re.MULTILINE)
    return match.group(1) if match else None


def graphify_version() -> str | None:
    if shutil.which("uv"):
        result = run(["uv", "tool", "list"])
        match = re.search(r"^graphifyy\s+v([0-9]+(?:\.[0-9]+)+)", result.stdout, re.MULTILINE)
        if match:
            return match.group(1)
    if shutil.which("pipx"):
        result = run(["pipx", "list", "--json"])
        try:
            return json.loads(result.stdout)["venvs"]["graphifyy"]["metadata"]["main_package"]["package_version"]
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
    return None


def _http_json(url: str, timeout: int = 10) -> object | None:
    """Fetch and parse a JSON document over HTTPS. Returns None on any failure."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "gbrain-graphify-doctor"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def latest_gbrain_version() -> str | None:
    """Latest official GBrain release (GitHub releases, falling back to tags)."""
    override = os.environ.get("GBRAIN_GRAPHIFY_LATEST_GBRAIN")
    if override:
        return override.strip() or None
    payload = _http_json("https://api.github.com/repos/garrytan/gbrain/releases/latest")
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    if isinstance(tag, str) and tag:
        return tag.lstrip("v")
    payload = _http_json("https://api.github.com/repos/garrytan/gbrain/tags")
    if isinstance(payload, list) and payload:
        name = payload[0].get("name")
        if isinstance(name, str) and name:
            return name.lstrip("v")
    return None


def latest_graphify_version() -> str | None:
    """Latest official Graphify release from PyPI."""
    override = os.environ.get("GBRAIN_GRAPHIFY_LATEST_GRAPHIFY")
    if override:
        return override.strip() or None
    payload = _http_json("https://pypi.org/pypi/graphifyy/json")
    if isinstance(payload, dict):
        info = payload.get("info")
        version = info.get("version") if isinstance(info, dict) else None
        if isinstance(version, str) and version:
            return version
    return None


def graphify_extras_health() -> dict[str, object]:
    if not shutil.which("uv"):
        return {"ok": False, "error": "uv command not found"}
    if not shutil.which("graphify-mcp"):
        return {"ok": False, "error": "graphify-mcp command not found (mcp extra missing)"}
    result = run(["uv", "tool", "dir"])
    if result.returncode != 0 or not result.stdout.strip():
        return {"ok": False, "error": result.stderr.strip() or "uv tool directory unavailable"}
    tool_root = Path(result.stdout.strip()) / "graphifyy"
    tool_python = tool_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not tool_python.is_file():
        return {"ok": False, "error": f"Graphify tool Python not found: {tool_python}"}
    probe = run([str(tool_python), "-c", "import jieba"])
    return {
        "ok": probe.returncode == 0,
        "python": str(tool_python.resolve()),
        "mcp": shutil.which("graphify-mcp"),
        "chinese": probe.returncode == 0,
        "error": None if probe.returncode == 0 else (probe.stderr.strip() or "jieba import failed"),
    }


def check_codex(expected_commands: dict[str, str] | None = None) -> dict[str, object]:
    if not shutil.which("codex"):
        return {"ok": False, "error": "codex command not found"}
    checks: dict[str, object] = {}
    for name in ("gbrain", "graphify"):
        result = run(["codex", "mcp", "get", name, "--json"])
        if result.returncode != 0:
            checks[name] = {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
            continue
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            checks[name] = {"ok": False, "error": str(error)}
            continue
        if not isinstance(data, dict):
            checks[name] = {"ok": False, "error": "Codex MCP response must be an object"}
            continue
        transport = data.get("transport", {})
        checks[name] = validate_stdio_entry(
            transport,
            name,
            (expected_commands or {}).get(name),
        )
    return {"ok": all(item.get("ok") for item in checks.values()), "servers": checks}


def check_claude(
    config_path: Path,
    expected_commands: dict[str, str] | None = None,
) -> dict[str, object]:
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        servers = data.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError("mcpServers must be an object")
        checks = {
            name: validate_stdio_entry(
                servers.get(name),
                name,
                (expected_commands or {}).get(name),
                require_type=True,
            )
            for name in ("gbrain", "graphify")
        }
        return {
            "ok": all(item.get("ok") for item in checks.values()),
            "config": str(config_path),
            "servers": checks,
        }
    except (OSError, json.JSONDecodeError, AttributeError, ValueError) as error:
        return {"ok": False, "config": str(config_path), "error": str(error)}


def check_antigravity(
    config_path: Path,
    expected_commands: dict[str, str] | None = None,
) -> dict[str, object]:
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        servers = data.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError("mcpServers must be an object")
        results = {
            name: validate_stdio_entry(
                servers.get(name),
                name,
                (expected_commands or {}).get(name),
                require_type=True,
            )
            for name in ("gbrain", "graphify")
        }
        return {
            "ok": all(result.get("ok") for result in results.values()),
            "config": str(config_path),
            "servers": results,
        }
    except (OSError, json.JSONDecodeError, AttributeError, ValueError) as error:
        return {"ok": False, "config": str(config_path), "error": str(error)}


def check_graph(workspace: Path) -> dict[str, object]:
    graph = workspace / "graphify-out" / "graph.json"
    if not graph.is_file():
        return {"ok": False, "path": str(graph), "error": "graph not found"}
    if not shutil.which("graphify"):
        return {"ok": False, "path": str(graph), "error": "graphify command not found"}
    result = run(["graphify", "god-nodes", "--json", "--graph", str(graph)], timeout=60)
    return {
        "ok": result.returncode == 0,
        "path": str(graph),
        "bytes": graph.stat().st_size,
        "error": None if result.returncode == 0 else (result.stderr.strip() or result.stdout.strip()),
    }


def check_platform_adapter(agent: str) -> dict[str, object]:
    """Check that graphify-mcp is available (shared dependency for all platforms)."""
    mcp_path = shutil.which("graphify-mcp")
    return {"ok": mcp_path is not None, "graphify_mcp_path": mcp_path}


def check_mcp_json(config_path: Path, platform: str = "") -> dict[str, object]:
    """Validate a host MCP file using its documented top-level server key."""
    if not config_path.is_file():
        return {"ok": False, "path": str(config_path), "error": "file not found"}
    try:
        raw = config_path.read_bytes()
        # Check for UTF-8 BOM
        has_bom = raw.startswith(b'\xef\xbb\xbf')
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return {"ok": False, "path": str(config_path), "error": str(error)}

    if not isinstance(data, dict):
        return {"ok": False, "path": str(config_path), "error": "configuration root must be an object"}
    root_key = schema_root(platform) if platform else "mcpServers"
    servers = data.get(root_key, {})
    results: dict[str, object] = {}

    if not isinstance(servers, dict):
        return {"ok": False, "path": str(config_path), "error": f"{root_key} must be an object"}

    for name in ("gbrain", "graphify"):
        results[name] = validate_stdio_entry(servers.get(name), name)

    return {
        "ok": all(v.get("ok") for v in results.values()),
        "path": str(config_path),
        "platform": platform or None,
        "schemaRoot": root_key,
        "has_bom": has_bom,
        "servers": results,
        "advice": (
            f"Each entry under {root_key} must use local stdio. "
            "Consult your platform's official MCP config documentation for the exact format."
        ),
    }


def check_file_host(
    agent: str,
    expected_commands: dict[str, str] | None = None,
) -> dict[str, object]:
    """Validate a user-level MCP file for WorkBuddy, Cursor, or VS Code."""
    config_path = default_config_path(agent)
    if config_path is None:
        return {"ok": False, "error": f"{agent} does not use a file MCP configuration"}
    result = check_mcp_json(config_path, agent)
    if not result.get("ok"):
        return result
    servers = result.get("servers")
    if not isinstance(servers, dict):
        return result
    for name, expected in (expected_commands or {}).items():
        item = servers.get(name)
        if isinstance(item, dict):
            exact = validate_stdio_entry(item, name, expected, require_type=True)
            servers[name] = exact
    result["ok"] = all(
        isinstance(value, dict) and value.get("ok") for value in servers.values()
    )
    return result


def check_no_bom(path: Path) -> dict[str, object]:
    """Check that a JSON file has no UTF-8 BOM."""
    if not path.is_file():
        return {"ok": False, "path": str(path), "error": "file not found"}
    raw = path.read_bytes()
    has_bom = raw.startswith(b'\xef\xbb\xbf')
    return {"ok": not has_bom, "path": str(path), "has_bom": has_bom}


def check_plugin_skills(skill_dir: Path) -> dict[str, object]:
    """Check that plugin skills are installed in the given directory."""
    expected = ["gbrain-graphify-setup", "project-knowledge-bootstrap", "gbrain-graphify-doctor"]
    results: dict[str, object] = {}
    for name in expected:
        skill_path = skill_dir / name / "SKILL.md"
        results[name] = {"ok": skill_path.is_file(), "path": str(skill_path)}
    return {
        "ok": all(v["ok"] for v in results.values()),
        "skills": results,
    }


def host_config_has_conflict(report: object) -> bool:
    if not isinstance(report, dict):
        return False
    servers = report.get("servers")
    if not isinstance(servers, dict):
        return False
    for server in servers.values():
        if not isinstance(server, dict) or server.get("ok"):
            continue
        if server.get("error") != "entry not found or not an object":
            return True
    return False


# Universal agent runtime skill directory, installed for ALL file-based platforms
# (Cursor, Trae, WorkBuddy, etc.) so skills are discoverable without repo clone.
AGENTS_RUNTIME_SKILL_DIR = ".agents/skills"

# Platform-specific skill directories checked in addition to the universal one.
PLATFORM_SKILL_DIRS: dict[str, list[str]] = {
    "workbuddy": [".workbuddy/skills"],
    "antigravity": [".gemini/config/skills"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", default="codex")
    parser.add_argument(
        "--mcp-json",
        type=Path,
        help="Check a platform's MCP config file for correct stdio entry format. "
              "Accepts any path; common locations are: "
              "~/.workbuddy/mcp.json (WorkBuddy), ~/.cursor/mcp.json (Cursor), "
              "~/.windsurf/mcp.json (Windsurf), etc.",
    )
    parser.add_argument(
        "--mcp-platform",
        choices=("workbuddy", "cursor", "vscode", "antigravity"),
        help="Schema used with --mcp-json (defaults to mcpServers).",
    )
    parser.add_argument(
        "--fix-bom",
        type=Path,
        help="Strip UTF-8 BOM from the specified mcp.json file and exit",
    )
    parser.add_argument(
        "--claude-config",
        type=Path,
        default=Path.home() / ".claude.json",
    )
    parser.add_argument(
        "--antigravity-config",
        type=Path,
        default=Path.home() / ".gemini" / "antigravity" / "mcp_config.json",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Verify an opt-in project Graphify adapter for the selected host.",
    )
    args = parser.parse_args()

    # --fix-bom is a standalone action: strip BOM and exit
    if args.fix_bom:
        result = fix_bom(args.fix_bom.resolve())
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    actual_gbrain = gbrain_version()
    actual_graphify = graphify_version()
    latest_gbrain = latest_gbrain_version()
    latest_graphify = latest_graphify_version()
    gbrain_path = shutil.which("gbrain")
    graphify_path = shutil.which("graphify")
    graphify_mcp_path = shutil.which("graphify-mcp")
    expected_commands = {
        "gbrain": gbrain_path or "",
        "graphify": graphify_mcp_path or "",
    }
    gbrain_path_ok = bool(gbrain_path and Path(gbrain_path).is_absolute())
    graphify_path_ok = bool(graphify_path and Path(graphify_path).is_absolute())
    graphify_mcp_path_ok = bool(graphify_mcp_path and Path(graphify_mcp_path).is_absolute())
    checks: dict[str, object] = {
        "gbrain_binary": {
            "ok": gbrain_path_ok and (latest_gbrain is None or actual_gbrain == latest_gbrain),
            "path": gbrain_path,
            "absolutePath": gbrain_path_ok,
            "version": actual_gbrain,
            "latest": latest_gbrain,
            "versionOk": (actual_gbrain == latest_gbrain) if latest_gbrain is not None else None,
            "versionCheck": "unknown" if latest_gbrain is None else (
                "ok" if actual_gbrain == latest_gbrain else "stale"
            ),
        },
        "graphify_binary": {
            "ok": graphify_path_ok and (latest_graphify is None or actual_graphify == latest_graphify),
            "path": graphify_path,
            "absolutePath": graphify_path_ok,
            "version": actual_graphify,
            "latest": latest_graphify,
            "versionOk": (actual_graphify == latest_graphify) if latest_graphify is not None else None,
            "versionCheck": "unknown" if latest_graphify is None else (
                "ok" if actual_graphify == latest_graphify else "stale"
            ),
        },
        "graphify_mcp_binary": {
            "ok": graphify_mcp_path_ok,
            "path": graphify_mcp_path,
            "absolutePath": graphify_mcp_path_ok,
        },
        "graphify_extras": graphify_extras_health(),
    }
    requested = {item.strip() for item in args.agents.split(",") if item.strip()}
    unsupported = requested - set(SUPPORTED_HOSTS)
    if unsupported:
        parser.error(f"unsupported agent(s): {', '.join(sorted(unsupported))}")
    if "codex" in requested:
        checks["mcp_codex"] = check_codex(expected_commands)
    if "claude" in requested:
        checks["mcp_claude"] = check_claude(args.claude_config, expected_commands)
    if "antigravity" in requested:
        checks["mcp_antigravity"] = check_antigravity(args.antigravity_config, expected_commands)
        checks["plugin_skills_antigravity"] = check_plugin_skills(
            Path.home() / ".gemini" / "config" / "skills"
        )
    for file_agent in ("workbuddy", "cursor", "vscode"):
        if file_agent in requested:
            checks[f"mcp_{file_agent}"] = check_file_host(file_agent, expected_commands)
            skill_dir = user_skill_path(file_agent)
            if skill_dir is not None:
                checks[f"plugin_skills_{file_agent}"] = check_plugin_skills(skill_dir)
    checks["gbrain_health"] = gbrain_health()
    if gbrain_path:
        checks["mcp_gbrain_protocol"] = mcp_handshake(gbrain_path, ["serve"])
    else:
        checks["mcp_gbrain_protocol"] = {"ok": False, "error": "gbrain command not found"}
    if graphify_mcp_path:
        checks["mcp_graphify_protocol"] = mcp_handshake(graphify_mcp_path, [])
    else:
        checks["mcp_graphify_protocol"] = {"ok": False, "error": "graphify-mcp command not found"}
    if args.mcp_json:
        checks["mcp_json_format"] = check_mcp_json(
            args.mcp_json.resolve(), args.mcp_platform or ""
        )
        checks["mcp_json_bom"] = check_no_bom(args.mcp_json.resolve())
    if args.workspace:
        workspace = args.workspace.resolve()
        for agent in requested:
            if agent == "cursor":
                rule = workspace / ".cursor" / "rules" / "graphify.mdc"
                checks["workspace_cursor_adapter"] = {
                    "ok": rule.is_file(),
                    "path": str(rule),
                }
            elif agent == "vscode":
                instructions = workspace / ".github" / "copilot-instructions.md"
                content = instructions.read_text(encoding="utf-8") if instructions.is_file() else ""
                checks["workspace_vscode_adapter"] = {
                    "ok": "## graphify" in content,
                    "path": str(instructions),
                }
    required_ok = True
    for name, value in checks.items():
        if not isinstance(value, dict) or not value.get("ok"):
            required_ok = False
        if name in {"gbrain_binary", "graphify_binary"} and value.get("versionCheck") == "stale":
            required_ok = False
    report: dict[str, object] = {"ok": required_ok, "checks": checks}

    if not required_ok:
        bootstrap = ".\\bootstrap.ps1" if os.name == "nt" else "bash ./bootstrap.sh"
        agent_flag = "-Agent" if os.name == "nt" else "--agent"
        upgrade_flag = "-Upgrade" if os.name == "nt" else "--upgrade"
        replace_flag = "-ReplaceConflicts" if os.name == "nt" else "--replace-conflicts"
        selected = sorted(requested)[0] if requested else "codex"
        base = f"{bootstrap} {agent_flag} {selected}"
        recovery: list[str] = []
        binaries = (checks["gbrain_binary"], checks["graphify_binary"])
        if any(item.get("path") and item.get("versionCheck") == "stale" for item in binaries):
            recovery.append(f"{base} {upgrade_flag}")
        elif any(not item.get("path") for item in binaries):
            recovery.append(base)
        if not checks["graphify_extras"].get("ok"):
            recovery.append(base)
        host_mcp_keys = {
            "mcp_codex",
            "mcp_claude",
            "mcp_antigravity",
            "mcp_workbuddy",
            "mcp_cursor",
            "mcp_vscode",
        }
        failed_hosts = [checks[key] for key in checks if key in host_mcp_keys and not checks[key].get("ok")]
        if failed_hosts:
            recovery.append(
                f"{base} {replace_flag}"
                if any(host_config_has_conflict(item) for item in failed_hosts)
                else base
            )
        if not checks["gbrain_health"].get("ok"):
            recovery.append("gbrain doctor --json")
        report["recovery"] = list(dict.fromkeys(recovery or [base]))

    # Append platform MCP doc guidance for each requested agent
    doc_hints: list[str] = []
    for agent in sorted(requested):
        url = platform_doc_url(agent)
        if url:
            doc_hints.append(f"  {agent}: {url}")
    if doc_hints:
        report["platform_mcp_docs"] = (
            "If MCP server configuration is rejected, consult the official docs:\n"
            + "\n".join(doc_hints)
        )

    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if required_ok else 1


if __name__ == "__main__":
    sys.exit(main())
