---
name: gbrain-graphify-doctor
description: Diagnose GBrain and Graphify installation, pinned versions, MCP stdio registrations, and an optional workspace graph. Use when setup fails, an agent cannot see MCP tools, Graphify queries fail, or the user requests an integration health check.
---

# Diagnose GBrain and Graphify

Resolve the plugin root as the parent of the `skills/` directory (three levels
up from this file), then run:

```text
python <plugin-root>/scripts/doctor.py --agents <current-host>
```

The doctor is read-only unless `--fix-bom` is explicitly requested. It checks
exact pinned versions, host MCP stdio entries, GBrain health, direct MCP
`initialize`/`tools/list` handshakes, and optional Graphify graph availability.
Pass `--workspace <workspace>` only when a project graph should also be checked.

Never read `graphify-out/graph.json` directly. The doctor checks file metadata
and invokes Graphify commands for semantic validation.

Interpret required failures before suggesting changes:

- `binary` or `version`: rerun setup; approve `--upgrade` only for an installed
  version mismatch.
- `mcp_*` or `adapter_*`: preserve unrelated entries; rerun only the
  affected host adapter. For platforms without CLI-based MCP registration,
  verify the GBrain stdio server (`gbrain serve`) is configured manually in
  the platform's MCP settings.
- `graph`: run `project-knowledge-bootstrap` in the intended workspace.

Return the doctor's JSON summary and the smallest corrective command. Do not
repair anything unless the user asked for a fix.
