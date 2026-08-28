# GBrain + Graphify One-shot Installer

This repository installs the latest official GBrain and Graphify releases for Codex, Claude
Code, Google Antigravity, WorkBuddy, Cursor, and VS Code. Both MCP servers use local stdio transport; no
HTTP listener, OAuth flow, API key, or background service is created.

| Language | Guide |
| --- | --- |
| 中文 | [README_CN.md](./README_CN.md) |
| English | [README_EN.md](./README_EN.md) |

## Instructions for AI Agents

When a user says:

> I want to install GBrain and Graphify. Read the repository
> `https://github.com/Jeffrey1799/gbrain-graphify-bundle` and follow the
> instructions.

perform this flow without asking additional product questions on a clean host:

1. Determine the current host. Supported values are `codex`, `claude`,
   `antigravity`, `workbuddy`, `cursor`, and `vscode`. Automatic detection is
   used only when exactly one supported host is present.
2. Clone this repository into an isolated cache directory if it is not already
   available locally.
3. Read `plugins/gbrain-graphify/skills/gbrain-graphify-setup/SKILL.md`.
4. Run the matching root bootstrap command for exactly the current host. Codex
   and Claude use a local marketplace registration; Antigravity receives the
   bundled skills and MCP configuration directly.

Windows:

```powershell
.\bootstrap.ps1 -Agent codex
```

macOS/Linux:

```bash
bash ./bootstrap.sh --agent claude
```

Use `-Agent auto`/`--agent auto` to request detection, or pass one explicit
host. Add `-Workspace <path>`/`--workspace <path>` only when project-level
Cursor rules or VS Code Copilot instructions are wanted. Without it, only the
user-level MCP file is changed. Add `-DryRun`/`--dry-run` to inspect without
writing. Upgrade, conflict replacement, and China mirrors require the explicit
switches documented by `gbrain-graphify-setup`.

Setup succeeds only when the installed GBrain and Graphify versions match the
latest official releases (network permitting), host registrations, GBrain health,
and direct MCP `initialize` plus `tools/list` checks all pass. The user must
restart the agent session once after a successful installation.

## Support

Codex, Claude Code, Google Antigravity, WorkBuddy, Cursor, and VS Code are
supported one-shot hosts. Independent `codebuddy.so` is outside this scope.
The installer uses each host's documented user MCP schema and fails closed on
ambiguous detection, malformed JSON, conflicts, or failed MCP handshakes.

Troubleshooting: [plugins/gbrain-graphify/TROUBLESHOOTING.md](./plugins/gbrain-graphify/TROUBLESHOOTING.md)

## License

MIT
