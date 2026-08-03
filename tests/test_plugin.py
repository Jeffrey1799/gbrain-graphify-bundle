from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import os
import shutil
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "gbrain-graphify"
SCRIPTS = PLUGIN / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


host_config = load_module("host_config", SCRIPTS / "host_config.py")
mcp_config = load_module("configure_mcp", SCRIPTS / "configure_mcp.py")
configure = load_module("configure_antigravity", SCRIPTS / "configure_antigravity.py")
doctor = load_module("doctor", SCRIPTS / "doctor.py")


class ManifestTests(unittest.TestCase):
    def test_json_files_parse(self) -> None:
        paths = [
            ROOT / ".claude-plugin" / "marketplace.json",
            PLUGIN / ".codex-plugin" / "plugin.json",
            PLUGIN / ".claude-plugin" / "plugin.json",
            SCRIPTS / "versions.json",
        ]
        for path in paths:
            with self.subTest(path=path):
                json.loads(path.read_text(encoding="utf-8"))

    def test_names_and_versions_are_consistent(self) -> None:
        codex = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        claude_market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(codex["name"], PLUGIN.name)
        self.assertEqual(claude["name"], PLUGIN.name)
        self.assertEqual(codex["version"], claude["version"])
        self.assertEqual(claude_market["plugins"][0]["version"], codex["version"])
        self.assertEqual(codex["version"], "1.0.2")

    def test_pinned_tool_manifest_is_consistent(self) -> None:
        versions = json.loads((SCRIPTS / "versions.json").read_text(encoding="utf-8"))
        notices = (PLUGIN / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertEqual(versions["graphify"]["extras"], ["mcp", "chinese"])
        self.assertIn(versions["gbrain"]["version"], notices)
        self.assertIn(versions["gbrain"]["commit"], notices)
        self.assertIn(versions["graphify"]["version"], notices)

    def test_repository_urls_are_canonical(self) -> None:
        stale = "github.com/Jeffrey1799/" + "getting-started-with-" + "gbrain-and-graphify"
        canonical = "github.com/Jeffrey1799/gbrain-graphify-bundle"
        paths = [
            ROOT / "README.md",
            ROOT / "README_CN.md",
            ROOT / "README_EN.md",
            PLUGIN / ".codex-plugin" / "plugin.json",
            PLUGIN / ".claude-plugin" / "plugin.json",
            PLUGIN / "skills" / "gbrain-graphify-setup" / "SKILL.md",
            ROOT / "getting-started-with-gbrain-and-graphify_CN.html",
            ROOT / "getting-started-with-gbrain-and-graphify_EN.html",
            ROOT / ".claude-plugin" / "marketplace.json",
        ]
        for path in paths:
            with self.subTest(path=path):
                content = path.read_text(encoding="utf-8-sig")
                self.assertNotIn(stale, content)
                self.assertIn(canonical, content)

    def test_root_bootstrap_entrypoints_exist(self) -> None:
        self.assertTrue((ROOT / "bootstrap.ps1").is_file())
        self.assertTrue((ROOT / "bootstrap.sh").is_file())

    def test_skills_have_no_placeholders(self) -> None:
        for path in (PLUGIN / "skills").glob("*/SKILL.md"):
            with self.subTest(path=path):
                content = path.read_text(encoding="utf-8")
                self.assertNotIn("TODO", content)
                self.assertTrue(content.startswith("---\nname:"))


class HostRegistryTests(unittest.TestCase):
    def test_registry_covers_supported_hosts_and_aliases(self) -> None:
        self.assertEqual(set(host_config.HOST_REGISTRY), set(host_config.SUPPORTED_HOSTS))
        self.assertEqual(host_config.canonical_agent("work-buddy"), "workbuddy")
        self.assertEqual(host_config.canonical_agent("vs-code"), "vscode")
        for host in host_config.SUPPORTED_HOSTS:
            self.assertIn("doc", host_config.HOST_REGISTRY[host])
            self.assertEqual(host_config.HOST_REGISTRY[host]["doctor"]["gbrainArgs"], ["serve"])
        self.assertEqual(host_config.project_adapter("cursor"), ["graphify", "cursor", "install"])
        self.assertEqual(host_config.project_adapter("vscode"), ["graphify", "vscode", "install"])

    def test_user_config_path_matrix(self) -> None:
        home = Path("/tmp/test-home")
        self.assertIsNone(host_config.default_config_path("codex", home=home))
        self.assertEqual(
            host_config.default_config_path("workbuddy", home=home),
            home / ".workbuddy" / "mcp.json",
        )
        self.assertEqual(
            host_config.default_config_path("cursor", home=home),
            home / ".cursor" / "mcp.json",
        )
        self.assertEqual(
            host_config.default_config_path(
                "vscode", home=home, environ={"APPDATA": "C:/Users/test/AppData/Roaming"}, system="Windows"
            ),
            Path("C:/Users/test/AppData/Roaming/Code/User/mcp.json"),
        )
        self.assertEqual(
            host_config.default_config_path("vscode", home=home, system="Darwin"),
            home / "Library/Application Support/Code/User/mcp.json",
        )
        self.assertEqual(
            host_config.default_config_path(
                "vscode", home=home, environ={"XDG_CONFIG_HOME": "/tmp/xdg"}, system="Linux"
            ),
            Path("/tmp/xdg/Code/User/mcp.json"),
        )

    def test_auto_detection_unique_multiple_and_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            only_cursor = lambda name: name == "cursor"
            self.assertEqual(
                host_config.resolve_agent("auto", home=home, command_exists=only_cursor),
                "cursor",
            )
            with self.assertRaisesRegex(ValueError, "multiple supported agents"):
                host_config.resolve_agent(
                    "auto", home=home, command_exists=lambda name: name in {"cursor", "code"}
                )
            with self.assertRaisesRegex(ValueError, "could not detect"):
                host_config.resolve_agent("auto", home=home, command_exists=lambda _name: False)


class SharedMcpConfigTests(unittest.TestCase):
    def test_schema_roots_and_dry_run_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for host, root in (("workbuddy", "mcpServers"), ("cursor", "mcpServers"), ("vscode", "servers")):
                path = Path(directory) / f"{host}.json"
                result = mcp_config.configure(
                    agent=host,
                    config_path=path,
                    gbrain_command="C:/tools/gbrain.exe",
                    graphify_command="C:/tools/graphify-mcp.exe",
                    dry_run=True,
                )
                self.assertTrue(result["changed"])
                self.assertEqual(result["schemaRoot"], root)
                self.assertFalse(path.exists())

    def test_invalid_json_conflict_and_replace_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            original = "{broken json\n"
            path.write_text(original, encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                mcp_config.configure(
                    agent="workbuddy",
                    config_path=path,
                    gbrain_command="/tools/gbrain",
                    graphify_command="/tools/graphify-mcp",
                )
            self.assertEqual(path.read_text(encoding="utf-8"), original)

            path.write_text(json.dumps({"mcpServers": {"gbrain": {"type": "stdio", "command": "/other", "args": ["serve"]}}}), encoding="utf-8")
            conflict = mcp_config.configure(
                agent="workbuddy",
                config_path=path,
                gbrain_command="/tools/gbrain",
                graphify_command="/tools/graphify-mcp",
            )
            self.assertEqual(conflict["conflicts"], ["gbrain"])
            self.assertIsNone(conflict["backup"])
            replaced = mcp_config.configure(
                agent="workbuddy",
                config_path=path,
                gbrain_command="/tools/gbrain",
                graphify_command="/tools/graphify-mcp",
                replace_conflicts=True,
            )
            self.assertTrue(replaced["changed"])
            self.assertIsNotNone(replaced["backup"])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(data["mcpServers"]), {"gbrain", "graphify"})


class AntigravityMergeTests(unittest.TestCase):
    def test_merge_preserves_unrelated_servers(self) -> None:
        current = {"theme": "dark", "mcpServers": {"other": {"command": "other"}}}
        desired = configure.desired_servers("gbrain", "graphify-mcp")
        merged, conflicts, changed = configure.merge_servers(current, desired, False)
        self.assertTrue(changed)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(merged["mcpServers"]["other"], {"command": "other"})

    def test_conflict_is_fail_closed(self) -> None:
        current = {"mcpServers": {"gbrain": {"command": "other-gbrain"}}}
        desired = configure.desired_servers("gbrain", "graphify-mcp")
        merged, conflicts, changed = configure.merge_servers(current, desired, False)
        self.assertEqual(conflicts, ["gbrain"])
        self.assertTrue(changed)
        self.assertEqual(merged["mcpServers"]["gbrain"], current["mcpServers"]["gbrain"])

    def test_replace_conflict_and_rerun_are_idempotent(self) -> None:
        desired = configure.desired_servers("gbrain", "graphify-mcp")
        current = {"mcpServers": {"gbrain": {"command": "wrong"}}}
        merged, conflicts, changed = configure.merge_servers(current, desired, True)
        self.assertEqual(conflicts, [])
        self.assertTrue(changed)
        rerun, conflicts, changed = configure.merge_servers(merged, desired, False)
        self.assertEqual(rerun, merged)
        self.assertEqual(conflicts, [])
        self.assertFalse(changed)

    def test_validate_servers_checks_exact_shape_but_allows_extra_fields(self) -> None:
        desired = configure.desired_servers("C:/tools/gbrain.exe", "C:/tools/graphify-mcp.exe")
        config = {
            "mcpServers": {
                "gbrain": {
                    "type": "stdio",
                    "command": "C:/tools/gbrain.exe",
                    "args": ["serve"],
                    "env": {},
                },
                "graphify": {
                    "type": "stdio",
                    "command": "C:/tools/not-graphify-mcp.exe",
                    "args": [],
                },
            }
        }
        self.assertEqual(configure.validate_servers(config, desired), ["graphify"])
        config["mcpServers"]["graphify"] = {
            "type": "stdio",
            "command": "C:/tools/graphify-mcp.exe",
            "args": [],
            "env": {"UNCHANGED": "1"},
        }
        merged, conflicts, changed = configure.merge_servers(config, desired, False)
        self.assertEqual(conflicts, [])
        self.assertFalse(changed)
        self.assertEqual(merged["mcpServers"], config["mcpServers"])

    def test_desired_servers_uses_stdio_commands(self) -> None:
        desired = configure.desired_servers("C:/gbrain/gbrain.exe", "graphify-mcp")
        self.assertEqual(
            desired["gbrain"],
            {
                "type": "stdio",
                "command": "C:/gbrain/gbrain.exe",
                "args": ["serve"],
                "disabled": False,
            },
        )
        self.assertEqual(
            desired["graphify"],
            {
                "type": "stdio",
                "command": "graphify-mcp",
                "args": [],
                "disabled": False,
            },
        )

    def test_atomic_write_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mcp.json"
            path.write_text('{"theme": "dark"}\n', encoding="utf-8")
            backup = configure.atomic_write(path, {"theme": "light"})
            self.assertIsNotNone(backup)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"theme": "light"})
            self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), {"theme": "dark"})

    def test_cli_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "mcp_config.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "configure_antigravity.py"),
                    "--config",
                    str(config),
                    "--gbrain-command",
                    "gbrain",
                    "--graphify-command",
                    "graphify-mcp",
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(config.exists())
            self.assertTrue(json.loads(result.stdout)["changed"])

    def test_invalid_json_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "mcp_config.json"
            original = "{invalid json\n"
            config.write_text(original, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "configure_antigravity.py"),
                    "--config",
                    str(config),
                    "--gbrain-command",
                    "gbrain",
                    "--graphify-command",
                    "graphify-mcp",
                    "--replace-conflicts",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_invalid_server_container_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "mcp_config.json"
            original = '{"unrelated": true, "mcpServers": []}\n'
            config.write_text(original, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "configure_antigravity.py"),
                    "--config",
                    str(config),
                    "--gbrain-command",
                    "gbrain",
                    "--graphify-command",
                    "graphify-mcp",
                    "--replace-conflicts",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_text(encoding="utf-8"), original)
            self.assertIn("invalid and was not modified", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


class DoctorTests(unittest.TestCase):
    def test_antigravity_check_accepts_stdio_entry(self) -> None:
        import shutil

        directory = tempfile.mkdtemp()
        try:
            config_path = Path(directory) / "mcp_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "gbrain": {
                                "type": "stdio",
                                "command": "C:/gbrain/gbrain.exe",
                                "args": ["serve"],
                                "disabled": False,
                            },
                            "graphify": {
                                "type": "stdio",
                                "command": "graphify-mcp",
                                "args": [],
                                "disabled": False,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = doctor.check_antigravity(config_path)
            self.assertTrue(result["ok"], f"antigravity check failed: {result}")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_mcp_handshake_requires_nonempty_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = Path(directory) / "server.py"
            server.write_text(
                """import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'stub','version':'1'}}}), flush=True)
    elif request.get('method') == 'tools/list':
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'tools':[{'name':'stub_tool','description':'test','inputSchema':{'type':'object'}}]}}), flush=True)
""",
                encoding="utf-8",
            )
            result = doctor.mcp_handshake(sys.executable, [str(server)], timeout=5)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["toolCount"], 1)

    def test_mcp_handshake_rejects_early_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = Path(directory) / "server.py"
            server.write_text("raise SystemExit(7)\n", encoding="utf-8")
            result = doctor.mcp_handshake(sys.executable, [str(server)], timeout=2)
            self.assertFalse(result["ok"])
            self.assertIn("exited with code 7", result["error"])

    def test_mcp_handshake_rejects_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = Path(directory) / "server.py"
            server.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
            result = doctor.mcp_handshake(sys.executable, [str(server)], timeout=1)
            self.assertFalse(result["ok"])
            self.assertIn("timed out", result["error"])

    def test_mcp_handshake_rejects_malformed_initialize_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = Path(directory) / "server.py"
            server.write_text(
                """import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':[]}), flush=True)
""",
                encoding="utf-8",
            )
            result = doctor.mcp_handshake(sys.executable, [str(server)], timeout=2)
            self.assertFalse(result["ok"])
            self.assertIn("invalid result", result["error"])

    def test_recovery_replaces_only_existing_conflicts(self) -> None:
        missing = {"ok": False, "servers": {
            "gbrain": {"ok": False, "error": "entry not found or not an object"},
        }}
        conflict = {"ok": False, "servers": {
            "gbrain": {"ok": False, "error": "unexpected command: wrong"},
        }}
        invalid = {"ok": False, "error": "invalid JSON"}
        self.assertFalse(doctor.host_config_has_conflict(missing))
        self.assertTrue(doctor.host_config_has_conflict(conflict))
        self.assertFalse(doctor.host_config_has_conflict(invalid))

    def test_gbrain_health_requires_database_connection(self) -> None:
        payload = {
            "schema_version": 2,
            "status": "warnings",
            "checks": [{"name": "connection", "status": "warn"}],
        }
        completed = subprocess.CompletedProcess(["gbrain"], 0, json.dumps(payload), "")
        with mock.patch.object(doctor.shutil, "which", return_value="/tools/gbrain"), \
                mock.patch.object(doctor, "run", return_value=completed):
            result = doctor.gbrain_health()
        self.assertFalse(result["ok"])
        self.assertFalse(result["connectionOk"])

        payload["checks"][0]["status"] = "ok"
        completed = subprocess.CompletedProcess(["gbrain"], 0, json.dumps(payload), "")
        with mock.patch.object(doctor.shutil, "which", return_value="/tools/gbrain"), \
                mock.patch.object(doctor, "run", return_value=completed):
            result = doctor.gbrain_health()
        self.assertTrue(result["ok"])

    def test_claude_check_uses_exact_json_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".claude.json"
            gbrain = str((Path(directory) / "gbrain").resolve())
            graphify = str((Path(directory) / "graphify-mcp").resolve())
            config.write_text(
                json.dumps({"mcpServers": {
                    "gbrain": {"type": "stdio", "command": gbrain, "args": ["serve"]},
                    "graphify": {"type": "stdio", "command": graphify, "args": []},
                }}),
                encoding="utf-8",
            )
            result = doctor.check_claude(config, {"gbrain": gbrain, "graphify": graphify})
            self.assertTrue(result["ok"], result)
            data = json.loads(config.read_text(encoding="utf-8"))
            data["mcpServers"]["gbrain"]["command"] = f"not-{gbrain}"
            config.write_text(json.dumps(data), encoding="utf-8")
            result = doctor.check_claude(config, {"gbrain": gbrain, "graphify": graphify})
            self.assertFalse(result["ok"])

    def test_graphify_extras_require_mcp_and_chinese(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tool_root = Path(directory) / "graphifyy"
            tool_python = tool_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            tool_python.parent.mkdir(parents=True)
            tool_python.write_text("", encoding="ascii")

            def fake_run(command: list[str], timeout: int = 15):
                if command[:3] == ["uv", "tool", "dir"]:
                    return subprocess.CompletedProcess(command, 0, f"{directory}\n", "")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(doctor.shutil, "which", side_effect=lambda name: f"/tools/{name}"), \
                    mock.patch.object(doctor, "run", side_effect=fake_run):
                result = doctor.graphify_extras_health()
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["chinese"])


class McpJsonTests(unittest.TestCase):
    """Tests for mcp.json generation targets like WorkBuddy, Cursor, etc."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_mcp_json(self, content: dict, add_bom: bool = False) -> Path:
        path = self.tmp / "mcp.json"
        text = json.dumps(content, indent=2)
        if add_bom:
            text = "\ufeff" + text
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_stdio_entries(self) -> None:
        config = {
            "mcpServers": {
                "gbrain": {
                    "type": "stdio",
                    "command": "C:/Users/test/.bun/bin/gbrain",
                    "args": ["serve"],
                    "disabled": False,
                },
                "graphify": {
                    "type": "stdio",
                    "command": "C:/Users/test/.local/bin/graphify-mcp",
                    "args": [],
                    "disabled": False,
                },
            }
        }
        path = self._make_mcp_json(config)
        result = doctor.check_mcp_json(path)
        self.assertTrue(result["ok"], f"mcp_json check failed: {result}")
        self.assertEqual(result["servers"]["gbrain"]["type"], "stdio")
        self.assertEqual(result["servers"]["graphify"]["type"], "stdio")

    def test_vscode_servers_root_is_validated(self) -> None:
        config = {
            "servers": {
                "gbrain": {
                    "type": "stdio",
                    "command": "C:/Users/test/.bun/bin/gbrain",
                    "args": ["serve"],
                },
                "graphify": {
                    "type": "stdio",
                    "command": "C:/Users/test/.local/bin/graphify-mcp",
                    "args": [],
                },
            }
        }
        result = doctor.check_mcp_json(self._make_mcp_json(config), "vscode")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["schemaRoot"], "servers")

    def test_non_object_json_root_is_rejected(self) -> None:
        path = self.tmp / "mcp.json"
        path.write_text("[]", encoding="utf-8")
        result = doctor.check_mcp_json(path, "vscode")
        self.assertFalse(result["ok"])
        self.assertIn("root must be an object", result["error"])

    def test_missing_type_field(self) -> None:
        config = {
            "mcpServers": {
                "gbrain": {
                    "command": "gbrain",
                    "args": ["serve"],
                },
                "graphify": {
                    "command": "graphify-mcp",
                    "args": [],
                },
            }
        }
        path = self._make_mcp_json(config)
        result = doctor.check_mcp_json(path)
        self.assertFalse(result["ok"])
        self.assertIn("stdio", str(result))

    def test_wrong_commands_are_rejected(self) -> None:
        config = {
            "mcpServers": {
                "gbrain": {"type": "stdio", "command": "not-gbrain", "args": ["serve"]},
                "graphify": {"type": "stdio", "command": "python", "args": []},
            }
        }
        result = doctor.check_mcp_json(self._make_mcp_json(config))
        self.assertFalse(result["ok"])
        self.assertFalse(result["servers"]["gbrain"]["ok"])
        self.assertFalse(result["servers"]["graphify"]["ok"])

    def test_file_host_doctor_checks_exact_absolute_commands(self) -> None:
        for host, root in (("workbuddy", "mcpServers"), ("cursor", "mcpServers"), ("vscode", "servers")):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "mcp.json"
                path.write_text(
                    json.dumps({
                        root: {
                            "gbrain": {"type": "stdio", "command": "/tools/gbrain", "args": ["serve"]},
                            "graphify": {"type": "stdio", "command": "/tools/graphify-mcp", "args": []},
                        }
                    }),
                    encoding="utf-8",
                )
                with mock.patch.object(doctor, "default_config_path", return_value=path):
                    result = doctor.check_file_host(
                        host,
                        {"gbrain": "/tools/gbrain", "graphify": "/tools/graphify-mcp"},
                    )
                self.assertTrue(result["ok"], result)
                path.write_text(path.read_text(encoding="utf-8").replace("/tools/gbrain", "/other"), encoding="utf-8")
                with mock.patch.object(doctor, "default_config_path", return_value=path):
                    result = doctor.check_file_host(
                        host,
                        {"gbrain": "/tools/gbrain", "graphify": "/tools/graphify-mcp"},
                    )
                self.assertFalse(result["ok"])

    def test_utf8_bom_is_detected(self) -> None:
        config = {"mcpServers": {}}
        path = self._make_mcp_json(config, add_bom=True)
        result = doctor.check_no_bom(path)
        self.assertFalse(result["ok"], "BOM should be detected")
        self.assertTrue(result["has_bom"])

    def test_no_bom_is_ok(self) -> None:
        config = {"mcpServers": {}}
        path = self._make_mcp_json(config, add_bom=False)
        result = doctor.check_no_bom(path)
        self.assertTrue(result["ok"])
        self.assertFalse(result["has_bom"])

    def test_missing_file_reports_error(self) -> None:
        missing = self.tmp / "does_not_exist.json"
        result = doctor.check_mcp_json(missing)
        self.assertFalse(result["ok"])
        self.assertIn("not found", result.get("error", ""))

    def test_invalid_json_reports_error(self) -> None:
        path = self.tmp / "mcp.json"
        path.write_text("{invalid json", encoding="utf-8")
        result = doctor.check_mcp_json(path)
        self.assertFalse(result["ok"])


class GuideTests(unittest.TestCase):
    def test_primary_guides_are_stdio_only(self) -> None:
        for path in (
            ROOT / "README.md",
            ROOT / "README_CN.md",
            ROOT / "README_EN.md",
            PLUGIN / "README_CN.md",
            PLUGIN / "README_EN.md",
            PLUGIN / "skills" / "gbrain-graphify-setup" / "SKILL.md",
        ):
            with self.subTest(path=path):
                content = path.read_text(encoding="utf-8-sig")
                self.assertNotIn("loopback " + "HTTP", content)
                self.assertNotIn("环回 HTTP", content)
                self.assertIn("stdio", content)

    def test_setup_success_output_is_minimal(self) -> None:
        for path in (SCRIPTS / "setup.ps1", SCRIPTS / "setup.sh"):
            with self.subTest(path=path):
                content = path.read_text(encoding="utf-8")
                self.assertIn("ok: true", content)
                self.assertIn("Restart the Agent session", content)
                self.assertNotIn("ZEROENTROPY_API_KEY", content)
                self.assertNotIn("OPENAI_API_KEY", content)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell only")
    def test_windows_bootstrap_dry_run(self) -> None:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "bootstrap.ps1"),
                "-Agent",
                "codex",
                "-DryRun",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Dry-run complete", result.stdout)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell only")
    def test_windows_setup_clean_host_dry_run_writes_nothing(self) -> None:
        powershell = shutil.which("powershell.exe")
        assert powershell is not None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            local_app_data = root / "local"
            home.mkdir()
            local_app_data.mkdir()
            env = os.environ.copy()
            env.update({
                "USERPROFILE": str(home),
                "HOME": str(home),
                "LOCALAPPDATA": str(local_app_data),
                "PATH": "",
            })
            baseline = subprocess.run(
                [powershell, "-NoProfile", "-Command", "exit 0"],
                env=env,
                capture_output=True,
                check=False,
            )
            self.assertEqual(baseline.returncode, 0, baseline.stderr.decode(errors="replace"))
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPTS / "setup.ps1"),
                    "-Agents",
                    "codex,claude,antigravity",
                    "-DryRun",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            after = sorted(path.relative_to(root) for path in root.rglob("*"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(after, before)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell only")
    def test_windows_setup_rejects_version_conflict_before_apply(self) -> None:
        powershell = shutil.which("powershell.exe")
        assert powershell is not None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            home = root / "home"
            local_app_data = root / "local"
            bin_dir.mkdir()
            home.mkdir()
            local_app_data.mkdir()
            (bin_dir / "gbrain.cmd").write_text("@echo off\necho gbrain 9.9.9\n", encoding="ascii")
            env = os.environ.copy()
            env.update({
                "USERPROFILE": str(home),
                "HOME": str(home),
                "LOCALAPPDATA": str(local_app_data),
                "PATH": str(bin_dir),
            })
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPTS / "setup.ps1"),
                    "-Agents",
                    "codex",
                    "-DryRun",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("GBrain 9.9.9 is installed", output)
            self.assertNotIn("Phase 2/3", output)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell only")
    def test_windows_setup_preserves_damaged_antigravity_json(self) -> None:
        powershell = shutil.which("powershell.exe")
        assert powershell is not None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            config = home / ".gemini" / "antigravity" / "mcp_config.json"
            config.parent.mkdir(parents=True)
            original = "{broken json\n"
            config.write_text(original, encoding="utf-8")
            local_app_data = root / "local"
            local_app_data.mkdir()
            env = os.environ.copy()
            env.update({
                "USERPROFILE": str(home),
                "HOME": str(home),
                "LOCALAPPDATA": str(local_app_data),
            })
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPTS / "setup.ps1"),
                    "-Agents",
                    "antigravity",
                    "-DryRun",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_text(encoding="utf-8"), original)
            self.assertIn("invalid and was not modified", result.stdout + result.stderr)

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "Unix Bash only")
    def test_unix_setup_claude_clean_config_dry_run_without_python(self) -> None:
        bash = shutil.which("bash")
        assert bash is not None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            bin_dir = root / "bin"
            home.mkdir()
            bin_dir.mkdir()
            (home / ".claude.json").write_text('{"unrelated": true}\n', encoding="utf-8")
            for name in ("dirname", "uname"):
                source = shutil.which(name)
                assert source is not None
                (bin_dir / name).symlink_to(source)
            claude = bin_dir / "claude"
            claude.write_text("#!/bin/sh\nexit 1\n", encoding="ascii")
            claude.chmod(0o755)
            env = os.environ.copy()
            env.update({"HOME": str(home), "PATH": str(bin_dir)})
            result = subprocess.run(
                [bash, str(SCRIPTS / "setup.sh"), "--agents", "claude", "--dry-run"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Dry-run complete", result.stdout)
            self.assertEqual((home / ".claude.json").read_text(encoding="utf-8"), '{"unrelated": true}\n')

    @unittest.skipIf(
        os.name == "nt" or not shutil.which("bash") or not shutil.which("python3"),
        "Unix Bash with Python 3 only",
    )
    def test_unix_setup_rejects_damaged_antigravity_json_before_apply(self) -> None:
        bash = shutil.which("bash")
        assert bash is not None
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            config = home / ".gemini" / "antigravity" / "mcp_config.json"
            config.parent.mkdir(parents=True)
            original = "{broken json\n"
            config.write_text(original, encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = str(home)
            result = subprocess.run(
                [
                    bash,
                    str(SCRIPTS / "setup.sh"),
                    "--agents",
                    "antigravity",
                    "--dry-run",
                    "--replace-conflicts",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Phase 2/3", output)
            self.assertIn("invalid and was not modified", output)
            self.assertEqual(config.read_text(encoding="utf-8"), original)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows PowerShell only")
    def test_windows_setup_accepts_existing_antigravity_json_without_optional_fields(self) -> None:
        powershell = shutil.which("powershell.exe")
        assert powershell is not None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            config = home / ".gemini" / "antigravity" / "mcp_config.json"
            config.parent.mkdir(parents=True)
            original = json.dumps({
                "unrelated": {"preserved": True},
                "mcpServers": {
                    "gbrain": {
                        "type": "stdio",
                        "command": "gbrain",
                        "args": ["serve"],
                    }
                },
            })
            config.write_text(original, encoding="utf-8")
            local_app_data = root / "local"
            local_app_data.mkdir()
            env = os.environ.copy()
            env.update({
                "USERPROFILE": str(home),
                "HOME": str(home),
                "LOCALAPPDATA": str(local_app_data),
                "PATH": "",
            })
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SCRIPTS / "setup.ps1"),
                    "-Agents",
                    "antigravity",
                    "-DryRun",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_guides_are_bootstrap_first(self) -> None:
        for name in (
            "getting-started-with-gbrain-and-graphify_CN.html",
            "getting-started-with-gbrain-and-graphify_EN.html",
        ):
            with self.subTest(name=name):
                content = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("bootstrap.ps1", content)
                self.assertIn("bootstrap.sh", content)
                self.assertIn("gbrain-graphify-setup", content)
                self.assertIn("project-knowledge-bootstrap", content)
                self.assertIn("graphify extract . --code-only", content)
                self.assertNotIn("raw.githubusercontent.com/" + "garrytan/gbrain", content)
                self.assertNotIn("raw.githubusercontent.com/" + "Graphify-Labs/graphify/v8", content)
                self.assertNotIn("graphifyy[mcp," + "pdf,office,watch]", content)
                self.assertGreaterEqual(content.lower().count("workbuddy"), 1)
                self.assertEqual(content.count("<details>"), content.count("</details>"))
                # Verify stdio MCP guidance is present for file-based platforms
                self.assertIn("mcp.json", content, "Guide should mention mcp.json for file-based platforms")
                self.assertIn("stdio", content.lower(), "Guide should mention stdio MCP mode")

    def test_guides_list_new_hosts_as_supported(self) -> None:
        for name in (
            "getting-started-with-gbrain-and-graphify_CN.html",
            "getting-started-with-gbrain-and-graphify_EN.html",
        ):
            with self.subTest(name=name):
                content = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("WorkBuddy", content)
                self.assertIn("Cursor", content)
                self.assertIn("VS Code", content)
                self.assertNotIn("Cursor, WorkBuddy, VS Code Copilot Chat, and other hosts are experimental", content)
                self.assertNotIn("Cursor、WorkBuddy、VS Code Copilot Chat 等其他宿主为实验性支持", content)


if __name__ == "__main__":
    unittest.main()
