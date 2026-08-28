---
name: gbrain-graphify-setup
description: Install or upgrade the latest official GBrain and Graphify releases, initialize local GBrain, register both tools as stdio MCP servers, and strictly verify Codex, Claude Code, Google Antigravity, WorkBuddy, Cursor, or VS Code. Use when the user asks to install, set up, configure, update, or connect GBrain and Graphify.
---

# Set up GBrain and Graphify

Resolve the repository or plugin root as the parent of `skills/`. From this file,
go up from `gbrain-graphify-setup/` to `skills/`, then to the plugin root. When
running from a repository checkout, the bootstrap entrypoints are two levels
above the plugin root (five parent directories above this `SKILL.md`).

## Supported hosts

Supported one-shot setup hosts are:

| Host | Windows | macOS/Linux | Graphify adapter |
| --- | --- | --- | --- |
| Codex | yes | yes | `graphify install --platform codex` |
| Claude Code | yes | yes | Windows: `--platform windows`; Unix: `graphify install` |
| Google Antigravity | yes | yes | `graphify antigravity install` |
| WorkBuddy | yes | yes | bundled user-level skills |
| Cursor | yes | yes | `graphify cursor install` with `--workspace` |
| VS Code | yes | yes | `graphify vscode install` with `--workspace`; user Copilot skills by default |

Independent `codebuddy.so` is outside the supported scope.

## Authorization and defaults

The user's instruction to read this repository and follow its installation
instructions authorizes a clean user-level install, plugin registration, and MCP
configuration. It does not authorize replacing an existing conflicting entry,
upgrading a different installed version, changing to a mirror, configuring API
keys, or modifying project files.

Defaults:

- local stdio MCP for both tools;
- GBrain PGLite with `--no-embedding`;
- Graphify extras `mcp,chinese`;
- official GitHub and PyPI sources only;
- exactly the current host, never all installed hosts.

## Execute

1. Identify the current host as `codex`, `claude`, `antigravity`, `workbuddy`,
   `cursor`, or `vscode`. Use `auto` only when detection finds exactly one.
2. If this is not already a checkout, clone
   `https://github.com/Jeffrey1799/gbrain-graphify-bundle` into an isolated cache.
3. Run a zero-write preflight, then run the same bootstrap without the dry-run
   flag if preflight succeeds.

Windows:

```powershell
.\bootstrap.ps1 -Agent codex -DryRun
.\bootstrap.ps1 -Agent codex
```

macOS/Linux:

```bash
bash ./bootstrap.sh --agent claude --dry-run
bash ./bootstrap.sh --agent claude
```

Use the current host value in both commands. Add `-Upgrade`/`--upgrade`,
`-ReplaceConflicts`/`--replace-conflicts`, or `-UseMirrorCN`/`--use-mirror-cn`
only when the user explicitly authorized that specific state change.

## Required verification

The setup script runs `scripts/doctor.py`. Do not claim success unless doctor
returns exit code 0 and JSON `ok: true`. Required checks include:

- latest official GBrain and Graphify versions (network permitting);
- expected host stdio command and arguments;
- `gbrain doctor --json`;
- MCP `initialize` and non-empty `tools/list` for `gbrain serve` and
  `graphify-mcp`;
- Host-specific skill or project adapter installation when requested.

The first line of the final user report must state that the Agent session must
be restarted before the new MCP tools appear. Also state that no project graph,
project rule file, paid model, or API key was configured.

## Failure behavior

Fail closed on invalid JSON, existing MCP conflicts, outdated tool versions, missing
permissions, unavailable official sources, failed GBrain health, or failed MCP
handshake. Consult `<plugin-root>/TROUBLESHOOTING.md` and report the smallest
recovery command. Never patch or commit the installer during a user's setup.

Upstream documentation remains authoritative for unsupported environments:

- GBrain: `https://github.com/garrytan/gbrain`
- Graphify: `https://github.com/Graphify-Labs/graphify`
