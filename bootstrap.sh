#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
agent=""
workspace=""
upgrade=0
replace_conflicts=0
use_mirror_cn=0
dry_run=0
marketplace_name="gbrain-graphify-guides"
plugin_id="gbrain-graphify@$marketplace_name"

while (($#)); do
  case "$1" in
    --agent) agent="${2:-}"; shift 2 ;;
    --workspace) workspace="${2:-}"; shift 2 ;;
    --upgrade) upgrade=1; shift ;;
    --replace-conflicts) replace_conflicts=1; shift ;;
    --use-mirror-cn) use_mirror_cn=1; shift ;;
    --dry-run) dry_run=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

resolve_agent() {
  if [[ -n "$agent" && "$agent" != "auto" ]]; then
    case "$agent" in
      codex|claude|antigravity|workbuddy|cursor|vscode) return 0 ;;
      *) echo "--agent must be auto, codex, claude, antigravity, workbuddy, cursor, or vscode" >&2; exit 2 ;;
    esac
  fi
  local candidates=()
  [[ -n "${GBRAIN_AGENT:-}" ]] && agent="$GBRAIN_AGENT" && resolve_agent && return
  command -v codex >/dev/null 2>&1 && candidates+=(codex)
  command -v claude >/dev/null 2>&1 && candidates+=(claude)
  [[ -d "$HOME/.gemini/antigravity" ]] && candidates+=(antigravity)
  { command -v workbuddy >/dev/null 2>&1 || [[ -d "$HOME/.workbuddy" ]]; } && candidates+=(workbuddy)
  { command -v cursor >/dev/null 2>&1 || [[ -d "$HOME/.cursor" ]]; } && candidates+=(cursor)
  vscode_config="${VSCODE_PORTABLE:-}/User/mcp.json"
  if [[ -z "${VSCODE_PORTABLE:-}" ]]; then
    if [[ "$(uname -s)" == Darwin ]]; then
      vscode_config="$HOME/Library/Application Support/Code/User/mcp.json"
    else
      vscode_config="${XDG_CONFIG_HOME:-$HOME/.config}/Code/User/mcp.json"
    fi
  fi
  { command -v code >/dev/null 2>&1 || command -v code-insiders >/dev/null 2>&1 || [[ -f "$vscode_config" ]]; } && candidates+=(vscode)
  if ((${#candidates[@]} == 1)); then agent="${candidates[0]}"; return; fi
  if ((${#candidates[@]} == 0)); then
    echo "Could not detect a supported agent; rerun with --agent codex, claude, antigravity, workbuddy, cursor, or vscode." >&2
  else
    echo "Multiple supported agents detected (${candidates[*]}); rerun with an explicit --agent." >&2
  fi
  exit 2
}
resolve_agent
if [[ -n "$workspace" ]]; then
  [[ -d "$workspace" ]] || { echo "Workspace does not exist: $workspace" >&2; exit 2; }
  workspace="$(cd "$workspace" && pwd -P)"
fi

step() { printf '[gbrain-graphify-bootstrap] %s\n' "$*"; }
run() {
  step "$*"
  if [[ "$dry_run" == 0 ]]; then "$@"; fi
}

register_codex() {
  if [[ "$dry_run" == 0 ]]; then command -v codex >/dev/null 2>&1 || { echo 'codex command not found' >&2; exit 1; }; fi
  local marketplaces plugins
  marketplaces="$(codex plugin marketplace list --json 2>/dev/null || true)"
  if grep -Fq "\"name\": \"$marketplace_name\"" <<<"$marketplaces"; then
    grep -Fq "$repo_root" <<<"$marketplaces" || { echo "Codex marketplace '$marketplace_name' points elsewhere" >&2; exit 1; }
    step 'Codex marketplace already registered from this checkout'
  else
    run codex plugin marketplace add "$repo_root"
  fi
  plugins="$(codex plugin list --json 2>/dev/null || true)"
  if grep -Fq "\"pluginId\": \"$plugin_id\"" <<<"$plugins"; then
    if [[ "$upgrade" == 1 ]]; then
      run codex plugin remove "$plugin_id"
      run codex plugin add "$plugin_id"
    else
      step 'Codex plugin already installed'
    fi
  else
    run codex plugin add "$plugin_id"
  fi
}

register_claude() {
  if [[ "$dry_run" == 0 ]]; then command -v claude >/dev/null 2>&1 || { echo 'claude command not found' >&2; exit 1; }; fi
  local marketplaces plugins
  marketplaces="$(claude plugin marketplace list --json 2>/dev/null || true)"
  if grep -Fq "\"name\": \"$marketplace_name\"" <<<"$marketplaces"; then
    grep -Fq "$repo_root" <<<"$marketplaces" || { echo "Claude marketplace '$marketplace_name' points elsewhere" >&2; exit 1; }
    step 'Claude marketplace already registered from this checkout'
    [[ "$upgrade" == 0 ]] || run claude plugin marketplace update "$marketplace_name"
  else
    run claude plugin marketplace add "$repo_root" --scope user
  fi
  plugins="$(claude plugin list --json 2>/dev/null || true)"
  if grep -Fq "\"id\": \"$plugin_id\"" <<<"$plugins"; then
    if [[ "$upgrade" == 1 ]]; then
      run claude plugin update "$plugin_id" --scope user
    else
      step 'Claude plugin already installed'
    fi
  else
    run claude plugin install "$plugin_id" --scope user
  fi
}

case "$agent" in
  codex) register_codex ;;
  claude) register_claude ;;
  antigravity) step 'Antigravity skills will be installed by setup' ;;
esac

setup_args=(--agents "$agent")
[[ -n "$workspace" ]] && setup_args+=(--workspace "$workspace")
[[ "$upgrade" == 1 ]] && setup_args+=(--upgrade)
[[ "$replace_conflicts" == 1 ]] && setup_args+=(--replace-conflicts)
[[ "$use_mirror_cn" == 1 ]] && setup_args+=(--use-mirror-cn)
[[ "$dry_run" == 1 ]] && setup_args+=(--dry-run)

step "Running setup for $agent"
bash "$repo_root/plugins/gbrain-graphify/scripts/setup.sh" "${setup_args[@]}"
