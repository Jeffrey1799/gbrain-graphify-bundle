# Troubleshooting

When the Agent encounters errors during setup/configuration, consult this file first.

---

## Windows PowerShell 5.1 Compatibility Pitfalls

All issues below were reproduced during real one-shot agent testing on Windows PowerShell 5.1 (not PS 7+).

### 1. First-run crash — `uv tool list` triggers NativeCommandError

| Item | Description |
|------|-------------|
| **Symptom** | Script aborts immediately on first run with `NativeCommandError` |
| **Root cause** | `uv tool list` writes to **stderr** when no tools are installed; PS 5.1 with `$ErrorActionPreference='Stop'` promotes stderr to a terminating error |
| **Fix** | Wrap the call in a local tolerance block with try/finally to restore the original preference: |

```powershell
$prev = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $listing = (& uv tool list 2>$null) -join "`n"
} finally {
    $ErrorActionPreference = $prev
}
```

---

### 2. Initialize GBrain without embeddings

| Item | Description |
|------|-------------|
| **Symptom** | Initialization requests an embedding provider or fails before creating the local database |
| **Root cause** | Plain `--pglite` can initialize the embedding pipeline |
| **Fix** | Run the pinned installer command directly in keyword-only mode |

```powershell
& gbrain init --pglite --no-embedding
if ($LASTEXITCODE -ne 0) { throw "gbrain init failed" }
```

---

### 3. `ConvertFrom-Json -AsHashtable` throws ParameterBindingException

| Item | Description |
|------|-------------|
| **Symptom** | Throws `A parameter cannot be found that matches parameter name 'AsHashtable'` |
| **Root cause** | `-AsHashtable` is a **PowerShell 7+** exclusive parameter; Windows PowerShell 5.1 does not support it |
| **Fix** | Replace with a manual deep-conversion helper: |

```powershell
function ConvertTo-HashtableDeep([object]$InputObject) {
    if ($InputObject -is [System.Management.Automation.PSCustomObject]) {
        $ht = @{}
        foreach ($prop in $InputObject.PSObject.Properties) {
            $ht[$prop.Name] = ConvertTo-HashtableDeep $prop.Value
        }
        return $ht
    }
    elseif ($InputObject -is [System.Collections.IEnumerable] -and $InputObject -isnot [string]) {
        return @($InputObject | ForEach-Object { ConvertTo-HashtableDeep $_ })
    }
    return $InputObject
}

# Usage
$config = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json | ConvertTo-HashtableDeep
```

---

### 4. Missing UTF-8 BOM causes garbled characters

| Item | Description |
|------|-------------|
| **Symptom** | Banner, comments, and special Unicode characters display as mojibake (GBK) in the terminal |
| **Root cause** | `.ps1` file saved as UTF-8 **without BOM**; PS 5.1 defaults to the system ANSI code page (GBK/CP936 on zh-CN Windows) |
| **Fix** | All `.ps1` scripts must be saved as **UTF-8 with BOM** (file header `EF BB BF`) |

```powershell
# Detect
$bytes = [System.IO.File]::ReadAllBytes($scriptPath)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)

# Fix: rewrite as UTF-8 with BOM
$content = [System.IO.File]::ReadAllText($scriptPath, [System.Text.Encoding]::UTF8)
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($scriptPath, $content, $utf8Bom)
```

---

## Installation & Runtime Issues

### `bun install -g` fails on Windows (Fail extracting tarball)

`bun install -g` may occasionally report `Fail extracting tarball` on Windows.
The setup script then downloads the pinned commit from the official GBrain
repository and compiles it locally. If both paths fail, do not build an
unpinned branch: fix the reported network, permission, or Bun error and rerun
the same root bootstrap command.

---

### GBrain PGLite initialization fails (Bun vfs / WASM)

The standalone `gbrain.exe` compiled via `bun build --compile` may have PGLite WASM issues on Windows:
```
PGLite failed to initialize its WASM runtime.
Bun vfs issue: `/$$bunfs/root` is read-only
```

**Fix:** Use the bun-installed shim at `~/.bun/bin/gbrain` (it works correctly), or run from the source tree with `bun run src/cli.ts`.

---

### MCP connectors not visible

If MCP tools are not showing up in the agent's UI after installation:

1. **Locate the supported host configuration**:

| Platform | Config file path |
|----------|-----------------|
| Codex | Managed via `codex mcp` CLI |
| Claude Code | `~/.claude.json` |
| Google Antigravity | `~/.gemini/antigravity/mcp_config.json` |
| WorkBuddy | `~/.workbuddy/mcp.json` (`mcpServers`) |
| Cursor | `~/.cursor/mcp.json` (`mcpServers`) |
| VS Code | `%APPDATA%\\Code\\User\\mcp.json` on Windows; `~/Library/Application Support/Code/User/mcp.json` on macOS; `$XDG_CONFIG_HOME/Code/User/mcp.json` or `~/.config/Code/User/mcp.json` on Linux (`servers`) |

The installer writes and verifies the three supported file-host configurations
using their documented schemas. Independent `codebuddy.so` is not supported.

2. **Check file encoding**: JSON files must NOT contain a UTF-8 BOM. PowerShell 5.1's `Set-Content -Encoding utf8` adds a BOM. Detect and fix with:
   ```bash
   python plugins/gbrain-graphify/scripts/doctor.py --fix-bom <your-config-path>
   ```

3. **Check fields**: Each MCP entry must include `"type": "stdio"`. Validate with:
   ```bash
   python plugins/gbrain-graphify/scripts/doctor.py --mcp-json <your-config-path>
   ```

4. **Consult official docs**: Each platform may require additional config fields. The doctor's `platform_mcp_docs` output provides official doc links. If the format written by the script differs from the platform's official format, **follow the official format**.

5. **Restart the agent session**: MCP connectors load at session start. Modifying the config file while the agent is running will NOT take effect until the next session.

6. **Manual fallback**: For a supported host, use the absolute executable paths
   reported by doctor. Configure GBrain with args `serve` and Graphify with no
   args. Do not replace an existing entry without explicit authorization.

---

### Git clone network errors

```
RPC failed; curl 56 schannel: server closed abruptly
```

Workarounds:
```bash
# Shallow clone (faster)
git clone --depth 1 https://github.com/Jeffrey1799/gbrain-graphify-bundle.git

# Or download as zip
curl -L https://github.com/Jeffrey1799/gbrain-graphify-bundle/archive/refs/heads/main.zip -o repo.zip
unzip repo.zip
```

---

### Doctor passes but MCP tools not working

If `doctor.py` reports `ok: true` but MCP tools are unavailable:

1. **Restart the agent session** — MCP connectors load at session start; config changes require a restart
2. **Verify the config path** — Make sure you are checking the correct config file for your platform (see table above)
3. **Verify command paths**: `which gbrain && which graphify-mcp` (or
   `Get-Command gbrain, graphify-mcp` on Windows)
4. **Rerun doctor**: it performs real MCP `initialize` and `tools/list`
   handshakes; a raw `{}` payload is not a valid protocol test
5. **Consult official docs**: the doctor's `platform_mcp_docs` output provides
   vendor documentation links

---

## Agent Code of Conduct

- When encountering any of the above errors, **fix first, then retry** — never silently skip a failed step.
- Do not patch or commit the installer during a user's setup. Report the failed
  check and the smallest recovery command.
- Mirror use changes the download trust source and must be explicitly enabled;
  setup never switches mirrors silently.
