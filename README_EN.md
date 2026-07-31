# Installing GBrain and Graphify

This repository delivers a pinned, verifiable installer for GBrain persistent
memory and Graphify local code graphs. GBrain and Graphify are registered as
local stdio MCP servers. They share user-level data without opening a port or
starting a resident service.

## One-shot Flow

Give your agent this prompt:

> I want to install GBrain and Graphify. Read the repository
> `https://github.com/Jeffrey1799/gbrain-graphify-bundle` and follow the
> instructions.

The agent must clone the repository, identify its current host, read the setup
skill, and run exactly one matching command:

```powershell
# Windows Codex example
.\bootstrap.ps1 -Agent codex
```

```bash
# macOS/Linux Claude Code example
bash ./bootstrap.sh --agent claude
```

Valid host values are `codex`, `claude`, `antigravity`, `workbuddy`, `cursor`,
and `vscode`. The bootstrap
registers this checkout as the local plugin marketplace when the host supports
marketplaces, installs the plugin,
installs pinned upstream tools, initializes keyword-only GBrain, configures the
host, and runs strict diagnostics.

Installing from a clean host is authorized by the original “follow the
instructions” prompt. The following still require explicit flags because they
can replace state or change the download trust source:

- `-Upgrade` / `--upgrade`
- `-ReplaceConflicts` / `--replace-conflicts`
- `-UseMirrorCN` / `--use-mirror-cn`

Use `-DryRun` or `--dry-run` for a zero-write preflight. Existing conflicting
MCP entries fail closed. Official GitHub and PyPI sources are used unless the
mirror flag is explicitly provided.

## Success Contract

Setup reports success only after all of these checks pass:

- exact pinned GBrain and Graphify versions;
- expected stdio command and arguments in the selected host;
- `gbrain doctor --json`;
- MCP `initialize` and `tools/list` against `gbrain serve` and `graphify-mcp`.

Restart the agent session after success so the host loads the new MCP entries.
No paid model, API key, project graph, or project rule file is configured.

## Supported File Hosts

WorkBuddy uses `~/.workbuddy/mcp.json` with `mcpServers`; Cursor uses
`~/.cursor/mcp.json` with `mcpServers`; VS Code uses the official user
`mcp.json` path with a `servers` root. All entries are local stdio and use
absolute executable paths. Independent `codebuddy.so` is not supported.

Use `-Workspace <path>`/`--workspace <path>` only when project-level Cursor
rules or VS Code Copilot instructions are wanted. User-level MCP setup remains
the default.

## Optional Project Bootstrap

After restarting, run `project-knowledge-bootstrap` in a project workspace to
build its Graphify graph and GBrain project memory. This is deliberately separate
because it modifies project-level files.

Detailed fallback material remains in the HTML guide and
[TROUBLESHOOTING.md](./plugins/gbrain-graphify/TROUBLESHOOTING.md).
