# GBrain + Graphify plugin

Supported one-shot hosts are Codex, Claude Code, Google Antigravity, WorkBuddy,
Cursor, and VS Code. The plugin
installs the latest official GBrain and Graphify releases and registers both through stdio
MCP. GBrain data persists under the user's profile; no HTTP service, OAuth flow,
or token is created.

Run the repository root bootstrap for the current host. Setup modifies only
user-level tool, plugin, and MCP state after the user's installation request.
Conflicts and upgrades fail closed unless explicitly authorized.

Independent `codebuddy.so` is outside the supported scope. See
`THIRD_PARTY_NOTICES.md` for upstream versions and licenses.
