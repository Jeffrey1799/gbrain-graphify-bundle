---
name: project-knowledge-bootstrap
description: Build, refresh, and verify BOTH a workspace-local Graphify AST code knowledge graph AND a GBrain persistent project memory brain. Use when starting work in a repository, initializing project knowledge, creating graphify-out/graph.json, distilling project architecture into ~/brain/projects/<slug>/, or enabling graph-first and brain-first exploration for Codex, Claude Code, or Google Antigravity.
---

# Bootstrap Project Knowledge (Graphify + GBrain)

Execute this skill to construct a complete two-tier project knowledge system for the workspace:
1. **Graphify AST Code Knowledge Graph**: Static code AST nodes, dependencies, god-nodes, and post-commit rebuild hooks (`graphify-out/graph.json`).
2. **GBrain Workspace Memory Brain**: Architecture distillation, git decision history, markdown cards in `~/brain/projects/<project-slug>/`, and PGLite database sync.

---

## Phase 1: Build Graphify Static AST Code Graph

1. Resolve the workspace root. Check whether `graphify-out/graph.json` exists.
   > ⚠️ **CRITICAL RULE**: Never execute `cat`, `grep`, `jq`, `sed`, `Get-Content`, or raw JSON readers directly on `graphify-out/graph.json`.
2. Extract AST code graph locally (code-only by default, zero paid API calls):
   ```text
   graphify extract . --code-only
   ```
3. Install Graphify Git hooks for automatic rebuilds on commit/checkout and conflict-free merge drivers:
   ```text
   graphify hook install
   ```
   Verify hook status with `graphify hook status`.
4. Validate graph generation via CLI:
   ```text
   graphify god-nodes --json
   graphify query "entry" --budget 500
   ```

---

## Phase 2: Build GBrain Workspace Project Brain & Memory

1. Resolve the project slug from repository name or `package.json` / `pyproject.toml` / `Cargo.toml`.
2. Ensure the local project brain directory exists:
   - Linux/macOS: `~/brain/projects/<project-slug>/`
   - Windows: `%USERPROFILE%\brain\projects\<project-slug>\`
3. Distill project knowledge by examining repository metadata, key entrypoints, configurations, and recent Git history (`git log --oneline -n 20` and `git show` on key architectural commits).
4. Create or update structural Markdown files in `~/brain/projects/<project-slug>/`.
5. Sync distilled markdown pages into the GBrain PGLite database:
   ```text
   gbrain sync
   ```
6. **Semantic Embedding (Optional)**: If an embedding key (`ZEROENTROPY_API_KEY` or `OPENAI_API_KEY`) is available in environment, run:
   ```text
   gbrain embed --stale
   ```

---

## Phase 3: Inject Project Rules & Agent Instructions

1. Install project-scoped adapter rules (`--strict` mode redirects raw file reads to graph query):
   - Codex: `graphify install --project --strict --platform codex`
   - Claude Code (Windows): `graphify install --project --strict --platform windows`
   - Claude Code (macOS/Linux): `graphify install --project --strict --platform claude`
   - Cursor / WorkBuddy / Others: `graphify install --project --strict --platform <platform-name>`
2. Append combined **Graphify MCP-First** and **GBrain Memory-First** rules to the workspace rules file (`CLAUDE.md`, `AGENTS.md`, or `.cursor/rules/graphify.mdc`):

   ```markdown
   ## Graphify AST Code Graph Exploration (System Guardrails)

   ### 1. Hard Anti-Pattern Block (CRITICAL FORBIDDEN RULE)
   - **Local Graph Check**: Before exploring the codebase, performing broad directory listings, or running native text/grep searches, check if `graphify-out/graph.json` exists in the workspace.
   - **NEVER READ GRAPH JSON DIRECTLY**: NEVER execute `cat`, `grep`, `jq`, `sed`, `Get-Content`, `view_file`, or any native file readers directly on `graphify-out/graph.json`. Doing so will instantly corrupt your context window with megabyte-level noise tokens and fail the task.

   ### 2. Mandatory Query Protocol (Single-Keyword Only)
   - **Single English Keyword Query**: For CLI (`graphify query "<keyword>"`) or MCP (`query_graph`), you MUST query using a **SINGLE English keyword** at a time (e.g., `query "drag"`, `query "import"`).
   - **STRICTLY BANNED**: NEVER query using multi-word phrases, natural-language sentences, or space-separated lists (e.g. `query "drag and drop"` is BANNED). Break down complex tasks into discrete, individual English keyword queries to match exact AST code symbols.
   - **Targeted Symbol Navigation**: Read and inspect ONLY the precise file paths, scoped subgraphs, and symbol dependencies returned by the graph output. Bypassing this via manual JSON parsing or unguided text searching is strictly forbidden.

   ### 3. Execution Priority & Tool Precedence
   1. **MCP Tools**: When available, invoke `query_graph` (single keyword), `get_node`, `get_neighbors`, or `shortest_path` for scoped AST symbol navigation.
   2. **CLI Command**: Fall back to executing `graphify query "<single_keyword>"` in the shell if MCP tools are unavailable.
   3. **Raw Search Fallback**: Use `grep` or file search strictly as a last resort when exact literal strings are missing from AST symbol nodes.

   ## GBrain Persistent Project Memory
   - **Memory-First**: Query local GBrain database (`gbrain search "<keyword>"` or `gbrain_query` / `gbrain_search`) before asking the user about prior project context, architectural decisions, or past work.
   - **Durable Write-Back**: After completing major features, refactors, or bug fixes, record durable project knowledge back into GBrain (`gbrain sync` or `put_page`).
   ```

---

## Phase 4: Validation & Report Synthesis

After completing Phase 1–3, report cleanly to the user:
- **Graphify Code Graph**: `graphify-out/graph.json` generated & git hooks installed (total god-nodes reported).
- **GBrain Project Brain**: `~/brain/projects/<project-slug>/` pages generated (list the actual pages created) & `gbrain sync` status.
- **Project Rules**: `AGENTS.md` / `CLAUDE.md` updated with Graphify & GBrain rules.
- **Verification Commands**:
  - `graphify god-nodes --json`
  - `gbrain search "<project-keyword>"`

