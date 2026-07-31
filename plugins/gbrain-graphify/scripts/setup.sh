#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
agents="codex"
workspace=""
upgrade=0
replace_conflicts=0
dry_run=0

use_mirror_cn=0
python_cmd=()

while (($#)); do
  case "$1" in
    --agents) agents="$2"; shift 2 ;;
    --workspace) workspace="$2"; shift 2 ;;
    --upgrade) upgrade=1; shift ;;
    --replace-conflicts) replace_conflicts=1; shift ;;
    --use-mirror-cn) use_mirror_cn=1; shift ;;
    --dry-run) dry_run=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

step() { printf '[gbrain-graphify] %s\n' "$*"; }
run() {
  step "$*"
  if [[ "$dry_run" == 0 ]]; then "$@"; fi
}

install_skills() {
  local target="$1"
  local src="$script_dir/../skills"
  if [[ "$dry_run" == 1 ]]; then
    step "copy plugin skills to $target"
    return
  fi
  mkdir -p "$target"
  for skill in gbrain-graphify-setup project-knowledge-bootstrap gbrain-graphify-doctor; do
    if [[ -d "$src/$skill" ]]; then
      cp -r "$src/$skill" "$target/"
      step "Plugin skill '$skill' installed to $target"
    else
      step "Warning: skill directory '$src/$skill' not found"
    fi
  done
}
require() { command -v "$1" >/dev/null 2>&1 || { echo "$1 is required" >&2; exit 1; }; }

as_root() {
  if [[ "$(id -u)" == 0 ]]; then "$@"; else sudo "$@"; fi
}

ensure_command() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    return 0
  fi
  if [[ "$dry_run" == 1 ]]; then
    step "would install $name"
    return 0
  fi
  case "$(uname -s)" in
    Darwin)
      case "$name" in
        bun)
          step "installing bun..."
          curl -fsSL https://bun.sh/install | bash
          ;;
        uv)
          step "installing uv..."
          curl -LsSf https://astral.sh/uv/install.sh | sh
          ;;
        curl)
          echo "curl should be pre-installed on macOS" >&2; exit 1 ;;
      esac
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        case "$name" in
          curl) step "installing curl via apt..."; as_root apt-get update; as_root apt-get install -y curl ;;
          bun) step "installing bun from the official installer..."; curl -fsSL https://bun.sh/install | bash ;;
          uv) step "installing uv from the official installer..."; curl -LsSf https://astral.sh/uv/install.sh | sh ;;
        esac
      elif command -v yum >/dev/null 2>&1; then
        case "$name" in
          curl) step "installing curl via yum..."; as_root yum install -y curl ;;
          bun) step "installing bun from the official installer..."; curl -fsSL https://bun.sh/install | bash ;;
          uv) step "installing uv from the official installer..."; curl -LsSf https://astral.sh/uv/install.sh | sh ;;
        esac
      else
        echo "unsupported package manager; install $name manually" >&2
        exit 1
      fi
      ;;
  esac
  export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "$name installation failed" >&2
    exit 1
  fi
}

ensure_python_runtime() {
  if command -v python3 >/dev/null 2>&1 && \
      python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    python_cmd=(python3)
    return
  fi
  if [[ "$dry_run" == 1 ]]; then
    step 'would install Python 3.11 through uv'
    python_cmd=(python3)
    return
  fi
  step 'installing Python 3.11 through uv...'
  uv python install 3.11
  local resolved
  resolved="$(uv python find 3.11)"
  [[ -x "$resolved" ]] || { echo 'uv installed Python 3.11 but its executable was not found' >&2; exit 1; }
  python_cmd=("$resolved")
}

python_available() { command -v "${python_cmd[0]}" >/dev/null 2>&1; }
claude_entry_exists() {
  command -v claude >/dev/null 2>&1 && claude mcp get "$1" >/dev/null 2>&1
}

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "setup.sh supports macOS and Linux; use setup.ps1 on Windows" >&2; exit 1 ;;
esac

IFS=',' read -r -a requested_agents <<< "$agents"
for requested_agent in "${requested_agents[@]}"; do
  case "$requested_agent" in
    codex|claude|antigravity|workbuddy|cursor|vscode) ;;
    *) echo "unsupported agent: $requested_agent" >&2; exit 2 ;;
  esac
done

if [[ -n "$workspace" ]]; then
  [[ -d "$workspace" ]] || { echo "Workspace does not exist: $workspace" >&2; exit 2; }
  workspace="$(cd "$workspace" && pwd -P)"
fi

contains_agent() { [[ ",$agents," == *",$1,"* ]]; }

host_config_path() {
  case "$1" in
    antigravity) printf '%s\n' "$HOME/.gemini/antigravity/mcp_config.json" ;;
    workbuddy) printf '%s\n' "$HOME/.workbuddy/mcp.json" ;;
    cursor) printf '%s\n' "$HOME/.cursor/mcp.json" ;;
    vscode)
      if [[ -n "${VSCODE_PORTABLE:-}" ]]; then
        printf '%s\n' "$VSCODE_PORTABLE/User/mcp.json"
      elif [[ "$(uname -s)" == Darwin ]]; then
        printf '%s\n' "$HOME/Library/Application Support/Code/User/mcp.json"
      else
        printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/Code/User/mcp.json"
      fi
      ;;
    *) return 1 ;;
  esac
}

file_host_helper() {
  [[ "$1" == antigravity ]] && printf '%s\n' "$script_dir/configure_antigravity.py" ||
    printf '%s\n' "$script_dir/configure_mcp.py"
}

step 'Phase 1/3: preflight'
if [[ "$dry_run" == 0 ]]; then
  contains_agent codex && require codex
  contains_agent claude && require claude
fi
ensure_command curl
ensure_command uv
ensure_python_runtime
ensure_command bun
if [[ "$dry_run" == 0 ]]; then
  export PATH="$HOME/.bun/bin:$(uv tool dir --bin):$HOME/.local/bin:$PATH"
fi

if command -v "${python_cmd[0]}" >/dev/null 2>&1; then
  gbrain_version="$("${python_cmd[@]}" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["gbrain"]["version"])' "$script_dir/versions.json")"
  gbrain_commit="$("${python_cmd[@]}" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["gbrain"]["commit"])' "$script_dir/versions.json")"
  graphify_version="$("${python_cmd[@]}" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["graphify"]["version"])' "$script_dir/versions.json")"
  graphify_extras="$("${python_cmd[@]}" -c 'import json,sys; print(",".join(json.load(open(sys.argv[1], encoding="utf-8"))["graphify"]["extras"]))' "$script_dir/versions.json")"
else
  gbrain_version='<pinned>'
  gbrain_commit='<pinned-commit>'
  graphify_version='<pinned>'
  graphify_extras='mcp,chinese'
fi

if command -v bun >/dev/null 2>&1 && command -v "${python_cmd[0]}" >/dev/null 2>&1 && ! bun --version | "${python_cmd[@]}" -c 'import sys; v=tuple(map(int, sys.stdin.read().strip().split(".")[:3])); raise SystemExit(0 if v >= (1,3,10) else 1)'; then
  echo "Bun 1.3.10+ required" >&2
  exit 1
fi

mcp_entry_state() {
  local source_kind="$1" name="$2" expected="$3" source="$4"
  "${python_cmd[@]}" - "$source_kind" "$name" "$expected" "$source" <<'PY'
import json
import os
import sys

kind, name, expected, source = sys.argv[1:]
try:
    if kind == "codex":
        entry = json.loads(source).get("transport")
    else:
        with open(source, encoding="utf-8") as handle:
            entry = json.load(handle).get("mcpServers", {}).get(name)
except (OSError, AttributeError, json.JSONDecodeError):
    raise SystemExit(2)

if entry is None:
    raise SystemExit(1)
if not isinstance(entry, dict) or entry.get("type") != "stdio":
    raise SystemExit(2)
command = entry.get("command")
args = entry.get("args", [])
expected_args = ["serve"] if name == "gbrain" else []
if not isinstance(command, str) or not isinstance(args, list):
    raise SystemExit(2)
normalize = lambda value: os.path.normcase(os.path.abspath(os.path.expanduser(value)))
raise SystemExit(0 if normalize(command) == normalize(expected) and args == expected_args else 2)
PY
}

assert_no_host_conflicts() {
  local current="" state=0 config="$HOME/.gemini/antigravity/mcp_config.json"
  local gbrain_candidate graphify_candidate
  gbrain_candidate="$(command -v gbrain 2>/dev/null || printf gbrain)"
  graphify_candidate="$(command -v graphify-mcp 2>/dev/null || printf graphify-mcp)"
  if contains_agent codex && command -v codex >/dev/null 2>&1; then
    current="$(codex mcp get gbrain --json 2>/dev/null || true)"
    if [[ -n "$current" ]]; then
      if mcp_entry_state codex gbrain "$gbrain_candidate" "$current"; then state=0; else state=$?; fi
      [[ "$state" != 1 ]] || state=2
      [[ "$state" -le 2 ]] || { echo "Could not validate Codex MCP entry 'gbrain'" >&2; exit 1; }
      if [[ "$state" == 2 && "$replace_conflicts" == 0 ]]; then
        echo "Codex MCP entry 'gbrain' conflicts; review and rerun with --replace-conflicts" >&2; exit 1
      fi
    fi
    current="$(codex mcp get graphify --json 2>/dev/null || true)"
    if [[ -n "$current" ]]; then
      if mcp_entry_state codex graphify "$graphify_candidate" "$current"; then state=0; else state=$?; fi
      [[ "$state" != 1 ]] || state=2
      [[ "$state" -le 2 ]] || { echo "Could not validate Codex MCP entry 'graphify'" >&2; exit 1; }
      if [[ "$state" == 2 && "$replace_conflicts" == 0 ]]; then
        echo "Codex MCP entry 'graphify' conflicts; review and rerun with --replace-conflicts" >&2; exit 1
      fi
    fi
  fi
  if contains_agent claude && [[ -f "$HOME/.claude.json" ]]; then
    for name in gbrain graphify; do
      if python_available || claude_entry_exists "$name"; then
        python_available || { echo "Python 3.10+ is required to validate existing Claude MCP entry '$name'" >&2; exit 1; }
        expected="$graphify_candidate"
        [[ "$name" == gbrain ]] && expected="$gbrain_candidate"
        if mcp_entry_state claude "$name" "$expected" "$HOME/.claude.json"; then state=0; else state=$?; fi
        [[ "$state" -le 2 ]] || { echo "Could not validate Claude MCP entry '$name'" >&2; exit 1; }
        if [[ "$state" == 2 && "$replace_conflicts" == 0 ]]; then
          echo "Claude MCP entry '$name' conflicts; review and rerun with --replace-conflicts" >&2; exit 1
        fi
      fi
    done
  fi
  for file_agent in antigravity workbuddy cursor vscode; do
    contains_agent "$file_agent" || continue
    config_path="$(host_config_path "$file_agent")"
    [[ -f "$config_path" ]] || continue
    python_available || { echo "Python 3.10+ is required to validate existing $file_agent MCP configuration at $config_path" >&2; exit 1; }
    helper="$(file_host_helper "$file_agent")"
    validate_args=("$helper")
    [[ "$file_agent" == antigravity ]] || validate_args+=(--platform "$file_agent")
    validate_args+=(--config "$config_path" --gbrain-command "$gbrain_candidate" --graphify-command "$graphify_candidate" --validate-only)
    if "${python_cmd[@]}" "${validate_args[@]}" >/dev/null; then state=0; else state=$?; fi
    case "$state" in
      0) ;;
      2)
        [[ "$replace_conflicts" == 1 ]] || {
          echo "$file_agent MCP configuration conflicts; review and rerun with --replace-conflicts" >&2
          exit 1
        }
        ;;
      *) echo "$file_agent MCP configuration is invalid and was not modified: $config_path" >&2; exit 1 ;;
    esac
  done
}

assert_no_host_conflicts

installed_gbrain=""
if command -v gbrain >/dev/null 2>&1; then
  installed_gbrain="$(gbrain --help 2>/dev/null | head -n 1 | awk '{print $2}')"
fi
if [[ -n "$installed_gbrain" && "$installed_gbrain" != "$gbrain_version" && "$upgrade" == 0 ]]; then
  echo "GBrain $installed_gbrain is installed; pinned version is $gbrain_version. Rerun with --upgrade after approval." >&2
  exit 1
fi
installed_graphify=""
if command -v uv >/dev/null 2>&1; then
  installed_graphify="$(uv tool list 2>/dev/null | awk '/^graphifyy v/{sub(/^v/, "", $2); print $2}' || true)"
fi
graphify_extras_ok=0
if [[ "$dry_run" == 1 ]] && command -v graphify-mcp >/dev/null 2>&1; then
  graphify_extras_ok=1
elif command -v uv >/dev/null 2>&1 && command -v graphify-mcp >/dev/null 2>&1; then
  graphify_tool_python="$(uv tool dir 2>/dev/null)/graphifyy/bin/python"
  if [[ -x "$graphify_tool_python" ]] && "$graphify_tool_python" -c 'import jieba' >/dev/null 2>&1; then
    graphify_extras_ok=1
  fi
fi
if [[ -n "$installed_graphify" && "$installed_graphify" != "$graphify_version" && "$upgrade" == 0 ]]; then
  echo "Graphify $installed_graphify is installed; pinned version is $graphify_version. Rerun with --upgrade after approval." >&2
  exit 1
fi

step 'Phase 2/3: apply'

# Install / verify GBrain
if [[ "$installed_gbrain" != "$gbrain_version" ]]; then
  if [[ "$dry_run" == 1 ]]; then
    step "bun install -g github:garrytan/gbrain#$gbrain_commit"
  elif ! bun install -g "github:garrytan/gbrain#$gbrain_commit"; then
    step "Bun global install failed; building the pinned source archive"
    build_dir="$(mktemp -d)"
    trap 'rm -rf -- "$build_dir"' EXIT
    gbrain_archive_url="https://codeload.github.com/garrytan/gbrain/tar.gz/$gbrain_commit"
    if [[ "$use_mirror_cn" == 1 ]]; then
      gbrain_archive_url="https://ghproxy.net/$gbrain_archive_url"
    fi
    curl --fail --location "$gbrain_archive_url" \
      --output "$build_dir/gbrain.tar.gz"
    mkdir -p "$build_dir/source" "$HOME/.local/bin"
    tar -xzf "$build_dir/gbrain.tar.gz" -C "$build_dir/source" --strip-components=1
    (cd "$build_dir/source" && bun install --frozen-lockfile && \
      bun build --compile --outfile "$HOME/.local/bin/gbrain" src/cli.ts)
    chmod 700 "$HOME/.local/bin/gbrain"
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

# Install / verify Graphify
if [[ "$installed_graphify" != "$graphify_version" || "$graphify_extras_ok" == 0 ]]; then
  if [[ "$use_mirror_cn" == 1 ]]; then
    step "Using Tsinghua PyPI mirror for Graphify installation"
    run uv tool install --force --index-url https://pypi.tuna.tsinghua.edu.cn/simple "graphifyy[$graphify_extras]==$graphify_version"
  else
    run uv tool install --force "graphifyy[$graphify_extras]==$graphify_version"
  fi
fi

# Initialize local GBrain state.
if [[ ! -f "$HOME/.gbrain/config.json" ]]; then
  run gbrain init --pglite --no-embedding
else
  step "GBrain already initialized at $HOME/.gbrain/config.json"
fi

gbrain_path="$(command -v gbrain 2>/dev/null || true)"
[[ -n "$gbrain_path" ]] || { [[ "$dry_run" == 1 ]] && gbrain_path='gbrain' || { echo 'gbrain command not found after installation' >&2; exit 1; }; }

# Platform-specific MCP configuration
configure_codex() {
  local name="$1" expected="$2"; shift 2
  local current="" state=1
  current="$(codex mcp get "$name" --json 2>/dev/null || true)"
  if [[ -n "$current" ]]; then
    if mcp_entry_state codex "$name" "$expected" "$current"; then state=0; else state=$?; fi
    [[ "$state" != 1 ]] || state=2
  fi
  if [[ "$state" == 0 ]]; then return; fi
  if [[ "$state" == 2 ]]; then
    [[ "$replace_conflicts" == 1 ]] || { echo "Codex MCP entry '$name' conflicts" >&2; exit 1; }
    run codex mcp remove "$name"
  fi
  run codex mcp add "$name" "$@"
}
configure_claude() {
  local name="$1" expected="$2"; shift 2
  local state=1 config="$HOME/.claude.json"
  if [[ -f "$config" ]] && { python_available || claude_entry_exists "$name"; }; then
    python_available || { echo "Python 3.10+ is required to validate existing Claude MCP entry '$name'" >&2; exit 1; }
    if mcp_entry_state claude "$name" "$expected" "$config"; then state=0; else state=$?; fi
  fi
  if [[ "$state" == 0 ]]; then return; fi
  if [[ "$state" == 2 ]]; then
    [[ "$replace_conflicts" == 1 ]] || { echo "Claude MCP entry '$name' conflicts" >&2; exit 1; }
    run claude mcp remove --scope user "$name"
  fi
  run claude mcp add --scope user "$@"
}

install_graphify_adapter() {
  local agent="$1"
  if [[ "$dry_run" == 1 ]]; then
    step "graphify adapter: $agent"
    return
  fi
  case "$agent" in
    antigravity)
      temp_dir="$(mktemp -d)"
      (cd "$temp_dir" && run graphify antigravity install)
      rm -rf -- "$temp_dir"
      ;;
    claude)
      run graphify install
      ;;
    workbuddy)
      install_skills "$HOME/.workbuddy/skills"
      ;;
    cursor)
      if [[ -z "$workspace" ]]; then
        step 'Cursor project adapter skipped; rerun with --workspace to write .cursor/rules.'
      else
        (cd "$workspace" && run graphify cursor install)
      fi
      ;;
    vscode)
      install_skills "$HOME/.copilot/skills"
      if [[ -n "$workspace" ]]; then
        (cd "$workspace" && run graphify vscode install)
      else
        step 'VS Code project adapter skipped; rerun with --workspace to write .github/copilot-instructions.md.'
      fi
      ;;
    *)
      run graphify install --platform "$agent"
      ;;
  esac
}

graphify_mcp="$(command -v graphify-mcp 2>/dev/null || true)"
[[ -n "$graphify_mcp" ]] || { [[ "$dry_run" == 1 ]] && graphify_mcp='graphify-mcp' || { echo 'graphify-mcp command not found after installation' >&2; exit 1; }; }

if contains_agent codex; then
  install_graphify_adapter codex
  configure_codex gbrain "$gbrain_path" -- "$gbrain_path" serve
  configure_codex graphify "$graphify_mcp" -- "$graphify_mcp"
fi
if contains_agent claude; then
  install_graphify_adapter claude
  configure_claude gbrain "$gbrain_path" --transport stdio gbrain -- "$gbrain_path" serve
  configure_claude graphify "$graphify_mcp" graphify -- "$graphify_mcp"
fi
if contains_agent antigravity; then
  install_graphify_adapter antigravity
  antigravity_skill_root="$HOME/.gemini/config/skills"
  run mkdir -p "$antigravity_skill_root"
  for skill_name in gbrain-graphify-setup project-knowledge-bootstrap gbrain-graphify-doctor; do
    run cp -R "$script_dir/../skills/$skill_name" "$antigravity_skill_root/"
  done
  config_args=("$script_dir/configure_antigravity.py" --gbrain-command "$gbrain_path" --graphify-command "$graphify_mcp")
  if [[ "$replace_conflicts" == 1 ]]; then config_args+=(--replace-conflicts); fi
  if [[ "$dry_run" == 1 ]]; then config_args+=(--dry-run); fi
  run "${python_cmd[@]}" "${config_args[@]}"
fi
for file_agent in workbuddy cursor vscode; do
  contains_agent "$file_agent" || continue
  install_graphify_adapter "$file_agent"
  config_path="$(host_config_path "$file_agent")"
  config_args=("$(file_host_helper "$file_agent")" --platform "$file_agent" --config "$config_path" \
    --gbrain-command "$gbrain_path" --graphify-command "$graphify_mcp")
  [[ "$replace_conflicts" == 1 ]] && config_args+=(--replace-conflicts)
  [[ "$dry_run" == 1 ]] && config_args+=(--dry-run)
  run "${python_cmd[@]}" "${config_args[@]}"
done

step 'Phase 3/3: verify'
if [[ "$dry_run" == 0 ]]; then
  doctor_args=("$script_dir/doctor.py" --agents "$agents")
  [[ -n "$workspace" ]] && doctor_args+=(--workspace "$workspace")
  run "${python_cmd[@]}" "${doctor_args[@]}"
fi
if [[ "$dry_run" == 1 ]]; then
  step 'Dry-run complete; no changes were applied.'
else
  step 'ok: true'
  step 'Restart the Agent session to load the gbrain and graphify MCP tools.'
fi
