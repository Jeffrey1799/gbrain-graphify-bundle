[CmdletBinding()]
param(
    [string[]]$Agents = @('codex'),
    [string]$Workspace,
    [switch]$Upgrade,
    [switch]$ReplaceConflicts,
    [switch]$SkipPrerequisiteInstall,
    [switch]$UseMirrorCN,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$versions = Get-Content -Raw -LiteralPath (Join-Path $scriptDir 'versions.json') | ConvertFrom-Json
$requestedAgents = @($Agents | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().ToLowerInvariant() } |
    Where-Object { $_ })
$supportedAgents = @('codex', 'claude', 'antigravity', 'workbuddy', 'cursor', 'vscode')
$unsupported = @($requestedAgents | Where-Object { $_ -notin $supportedAgents })
if ($unsupported) { throw "Unsupported agent(s): $($unsupported -join ', ')." }
if ($Workspace) {
    $Workspace = [IO.Path]::GetFullPath($Workspace)
    if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
        throw "Workspace does not exist: $Workspace"
    }
}
$script:ClaudeConfigPresent = @()
$script:ClaudeConfigConflicts = @()

function Write-Step([string]$Message) {
    Write-Output "[gbrain-graphify] $Message"
}

function Resolve-ToolPath([string]$Name) {
    $commands = @(Get-Command $Name -All -ErrorAction SilentlyContinue)
    $command = $commands | Where-Object { $_.CommandType -eq 'Application' } | Select-Object -First 1
    if (-not $command) { $command = $commands | Select-Object -First 1 }
    if ($command) { return $command.Source }
    if ($DryRun) { return $Name }
    throw "$Name command not found"
}

function Invoke-Tool([string]$File, [string[]]$Arguments) {
    Write-Step ("{0} {1}" -f $File, ($Arguments -join ' '))
    if ($DryRun) { return }
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File exited with code $LASTEXITCODE" }
}

function Refresh-UserPath {
    $paths = @(
        (Join-Path $env:USERPROFILE '.bun\bin'),
        (Join-Path $env:USERPROFILE '.local\bin'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links')
    )
    $existing = @(
        [Environment]::GetEnvironmentVariable('Path', 'User') -split ';'
        [Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';'
        $env:PATH -split ';'
    ) | Where-Object { $_ }
    $env:PATH = (($paths + $existing | Select-Object -Unique) -join ';')
}

function Ensure-Command([string]$Name, [string]$WingetId) {
    if (Get-Command $Name -ErrorAction SilentlyContinue) { return }
    if ($SkipPrerequisiteInstall) { throw "$Name is required but was not found" }
    if ($DryRun) {
        Write-Step "install prerequisite $Name from winget package $WingetId"
        return
    }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "$Name is missing and winget is unavailable. Install $Name from its official distribution first."
    }
    Invoke-Tool $winget.Source @(
        'install', '--id', $WingetId, '--exact', '--silent',
        '--accept-package-agreements', '--accept-source-agreements'
    )
    Refresh-UserPath
    if (-not $DryRun -and -not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was installed but is not discoverable on PATH; reopen the terminal and rerun setup"
    }
}

function Test-Python310 {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python -or $python.Source -match '(?i)\\WindowsApps\\python(?:3)?\.exe$') { return $false }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        & $python.Source -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Ensure-Python {
    if (Test-Python310) { return }
    if ($SkipPrerequisiteInstall) { throw 'Python 3.10+ is required but was not found' }
    if ($DryRun) {
        Write-Step 'install prerequisite python from winget package Python.Python.3.11'
        return
    }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Python 3.10+ is missing and winget is unavailable. Install Python from https://python.org and rerun.'
    }
    Invoke-Tool $winget.Source @(
        'install', '--id', 'Python.Python.3.11', '--exact', '--silent',
        '--accept-package-agreements', '--accept-source-agreements'
    )
    Refresh-UserPath
    if (-not (Test-Python310)) {
        throw 'Python 3.11 was installed but is not discoverable on PATH; reopen the terminal and rerun setup'
    }
}

function Get-GBrainVersion {
    if (-not (Get-Command gbrain -ErrorAction SilentlyContinue)) { return $null }
    $line = (& gbrain --help 2>$null | Select-Object -First 1)
    if ($line -match '^gbrain\s+([0-9]+(?:\.[0-9]+)+)') { return $Matches[1] }
    return $null
}

function Get-GraphifyVersion {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { return $null }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $listing = (& uv tool list 2>$null) -join "`n"
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($listing -match '(?m)^graphifyy\s+v([0-9]+(?:\.[0-9]+)+)') { return $Matches[1] }
    return $null
}

function Test-GraphifyExtras {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue) -or
        -not (Get-Command graphify-mcp -ErrorAction SilentlyContinue)) { return $false }
    if ($DryRun) { return $true }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $toolRoot = (& uv tool dir 2>$null | Select-Object -First 1)
        $toolPython = Join-Path $toolRoot 'graphifyy\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $toolPython)) { return $false }
        & $toolPython -c 'import jieba' 2>$null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Ensure-GBrainInit {
    $configPath = Join-Path $env:USERPROFILE '.gbrain\config.json'
    if (Test-Path -LiteralPath $configPath) {
        Write-Step "GBrain already initialized at $configPath"
        return
    }
    if ($DryRun) {
        Write-Step "gbrain init --pglite --no-embedding"
        return
    }
    Invoke-Tool (Resolve-ToolPath 'gbrain') @('init', '--pglite', '--no-embedding')
}

function Get-GBrainPath {
    return Resolve-ToolPath 'gbrain'
}

function Install-GBrainFallback {
    param([string]$CommitHash)
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('gbrain-fallback-' + [guid]::NewGuid().ToString('N'))
    $binDir = Join-Path $env:LOCALAPPDATA 'GBrainGraphify\bin'
    $output = Join-Path $binDir 'gbrain.exe'
    $archive = Join-Path $tempRoot 'gbrain-source.zip'

    try {
        New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
        $uri = "https://github.com/garrytan/gbrain/archive/$CommitHash.zip"
        if ($UseMirrorCN) {
            $uri = "https://ghproxy.net/https://github.com/garrytan/gbrain/archive/$CommitHash.zip"
            Write-Step "Using CN Mirror for GBrain source download: $uri"
        } else {
            Write-Step "Downloading GBrain source (commit $CommitHash)..."
        }
        Invoke-WebRequest -Uri $uri -OutFile $archive -UseBasicParsing

        Write-Step "Extracting source..."
        Expand-Archive -LiteralPath $archive -DestinationPath $tempRoot

        $source = Get-ChildItem -LiteralPath $tempRoot -Directory -Filter 'gbrain-*' | Select-Object -First 1
        if (-not $source) { throw 'GBrain source archive did not contain a source directory' }

        New-Item -ItemType Directory -Force -Path $binDir | Out-Null
        Push-Location $source.FullName
        try {
            Invoke-Tool (Resolve-ToolPath 'bun') @('install', '--frozen-lockfile')
            Invoke-Tool (Resolve-ToolPath 'bun') @(
                'build', '--compile', '--outfile', $output, 'src/cli.ts'
            )
        } finally {
            Pop-Location
        }
    } finally {
        if ($tempRoot.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $segments = @($userPath -split ';' | Where-Object { $_ })
    if ($binDir -notin $segments) {
        [Environment]::SetEnvironmentVariable('Path', ((@($binDir) + $segments) -join ';'), 'User')
    }
    $env:PATH = "$binDir;$env:PATH"
    Write-Step "GBrain fallback build complete: $output"
}

function Assert-PinnedVersions {
    if (Get-Command bun -ErrorAction SilentlyContinue) {
        $bunVersion = & bun --version 2>&1
        if ($bunVersion -match '([0-9]+\.[0-9]+(?:\.[0-9]+)?)' -and
            [version]$Matches[1] -lt [version]'1.3.10') {
            throw "Bun 1.3.10+ required, found $($bunVersion.Trim())"
        }
    }

    $gbrainVersion = Get-GBrainVersion
    $expectedGBrain = [string]$versions.gbrain.version
    if ($gbrainVersion -and $gbrainVersion -ne $expectedGBrain -and -not $Upgrade) {
        throw "GBrain $gbrainVersion is installed; pinned version is $expectedGBrain. Rerun with -Upgrade after approval."
    }
    $graphifyVersion = Get-GraphifyVersion
    $expectedGraphify = [string]$versions.graphify.version
    if ($graphifyVersion -and $graphifyVersion -ne $expectedGraphify -and -not $Upgrade) {
        throw "Graphify $graphifyVersion is installed; pinned version is $expectedGraphify. Rerun with -Upgrade after approval."
    }
}

function Ensure-PinnedTools {
    Ensure-Command 'bun' 'Oven-sh.Bun'
    Ensure-Command 'uv' 'astral-sh.uv'
    Ensure-Python
    Assert-PinnedVersions

    $gbrainVersion = Get-GBrainVersion
    $expectedGBrain = [string]$versions.gbrain.version
    if ($gbrainVersion -ne $expectedGBrain) {
        $source = "github:garrytan/gbrain#$($versions.gbrain.commit)"
        $usedFallback = $false
        try {
            Invoke-Tool (Resolve-ToolPath 'bun') @('install', '-g', $source)
        } catch {
            Write-Step "Bun global install failed: $($_.Exception.Message)"
            # Bun may return non-zero on Windows while still creating a working shim.
            # Check if gbrain is actually available before falling back.
            Refresh-UserPath
            $installedVersion = Get-GBrainVersion
            if ($installedVersion -eq $expectedGBrain) {
                Write-Step "GBrain shim found at $(Resolve-ToolPath 'gbrain'); using it despite install warning."
            } else {
                Write-Step "GBrain not available after bun install; attempting fallback build from source..."
                try {
                    Install-GBrainFallback -CommitHash $versions.gbrain.commit
                    $usedFallback = $true
                } catch {
                    throw "GBrain installation failed: bun install -g AND fallback build both failed. " +
                          "Manually clone https://github.com/garrytan/gbrain.git and run: bun install && bun run build"
                }
            }
        }
        if (-not $DryRun) { Refresh-UserPath }
        if ($usedFallback) {
            $fallbackBin = Join-Path $env:LOCALAPPDATA 'GBrainGraphify\bin'
            $env:PATH = "$fallbackBin;$env:PATH"
        }
    }

    $graphifyVersion = Get-GraphifyVersion
    $expectedGraphify = [string]$versions.graphify.version
    if ($graphifyVersion -ne $expectedGraphify -or -not (Test-GraphifyExtras)) {
        $extras = ($versions.graphify.extras | Where-Object { $_ }) -join ','
        $package = "graphifyy[$extras]==$expectedGraphify"
        $uvArgs = @('tool', 'install', '--force')
        if ($UseMirrorCN) {
            $uvArgs += @('--index-url', 'https://pypi.tuna.tsinghua.edu.cn/simple')
            Write-Step "Using Tsinghua PyPI mirror for Graphify installation"
        }
        $uvArgs += $package
        Invoke-Tool (Resolve-ToolPath 'uv') $uvArgs
        if (-not $DryRun) { Refresh-UserPath }
    }
}

function Get-CodexServer([string]$Name) {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { return $null }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $raw = & codex mcp get $Name --json 2>$null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) { return $null }
    return (($raw -join "`n") | ConvertFrom-Json)
}

function Ensure-CodexMcp([string]$Name, [string]$Command, [string[]]$CommandArgs) {
    $current = Get-CodexServer $Name
    if ($current) {
        $transport = $current.transport
        $currentArgs = @($transport.args)
        $currentCommand = [string]$transport.command
        $sameArgs = ($currentArgs.Count -eq $CommandArgs.Count) -and
            (($currentArgs -join [char]0) -ceq ($CommandArgs -join [char]0))
        if ([string]$transport.type -eq 'stdio' -and
            $currentCommand -and
            [IO.Path]::GetFullPath($currentCommand) -eq [IO.Path]::GetFullPath($Command) -and
            $sameArgs) { return }
        if (-not $ReplaceConflicts) { throw "Codex MCP entry '$Name' conflicts with the requested configuration." }
        Invoke-Tool (Resolve-ToolPath 'codex') @('mcp', 'remove', $Name)
    }
    Invoke-Tool (Resolve-ToolPath 'codex') (@('mcp', 'add', $Name, '--', $Command) + $CommandArgs)
}

function Ensure-ClaudeMcp([string]$Name, [string]$Command, [string[]]$CommandArgs) {
    if ($Name -in $script:ClaudeConfigConflicts) {
        Invoke-Tool (Resolve-ToolPath 'claude') @('mcp', 'remove', '--scope', 'user', $Name)
    } elseif ($Name -in $script:ClaudeConfigPresent) {
        return
    }
    Invoke-Tool (Resolve-ToolPath 'claude') (@('mcp', 'add', '--scope', 'user', $Name, '--', $Command) + $CommandArgs)
}

function Test-ClaudeServerExists([string]$Name) {
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { return $false }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        & claude mcp get $Name 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-HostConfigPath([string]$Agent) {
    switch ($Agent) {
        'antigravity' { return Join-Path $env:USERPROFILE '.gemini\antigravity\mcp_config.json' }
        'workbuddy' { return Join-Path $env:USERPROFILE '.workbuddy\mcp.json' }
        'cursor' { return Join-Path $env:USERPROFILE '.cursor\mcp.json' }
        'vscode' {
            $appData = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $env:USERPROFILE 'AppData\Roaming' }
            return Join-Path $appData 'Code\User\mcp.json'
        }
        default { return $null }
    }
}

function Get-FileHostHelper([string]$Agent) {
    if ($Agent -eq 'antigravity') {
        return Join-Path $scriptDir 'configure_antigravity.py'
    }
    return Join-Path $scriptDir 'configure_mcp.py'
}

function Get-FileHostPlatform([string]$Agent) {
    if ($Agent -eq 'antigravity') { return 'antigravity' }
    return $Agent
}

function Configure-FileMcp([string]$Agent, [string]$ConfigPath, [string]$GBrain, [string]$Graphify) {
    $arguments = @(
        (Get-FileHostHelper $Agent)
    )
    if ($Agent -ne 'antigravity') { $arguments += @('--platform', (Get-FileHostPlatform $Agent)) }
    $arguments += @(
        '--config', $ConfigPath,
        '--gbrain-command', $GBrain,
        '--graphify-command', $Graphify
    )
    if ($ReplaceConflicts) { $arguments += '--replace-conflicts' }
    if ($DryRun) { $arguments += '--dry-run' }
    Invoke-Tool (Resolve-ToolPath 'python') $arguments
}

function Install-GraphifyAdapter([string]$Agent) {
    if ($DryRun) { Write-Step "graphify adapter: $Agent"; return }
    if ($Agent -eq 'antigravity') {
        $temp = Join-Path ([IO.Path]::GetTempPath()) ("gbrain-graphify-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $temp | Out-Null
        try {
            Push-Location $temp
            & graphify antigravity install
            if ($LASTEXITCODE -ne 0) { throw "graphify Antigravity adapter exited with code $LASTEXITCODE" }
        } finally {
            Pop-Location
            if ($temp.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase)) {
                Remove-Item -LiteralPath $temp -Recurse -Force
            }
        }
        return
    }
    if ($Agent -eq 'workbuddy') {
        Install-PluginSkillsTo -TargetRoot (Join-Path $env:USERPROFILE '.workbuddy\skills')
        return
    }
    $graphify = Resolve-ToolPath 'graphify'
    if ($Agent -eq 'cursor') {
        if (-not $Workspace) {
            Write-Step 'Cursor project adapter skipped; rerun with -Workspace to write .cursor/rules.'
            return
        }
        Push-Location $Workspace
        try { Invoke-Tool $graphify @('cursor', 'install') } finally { Pop-Location }
        return
    }
    if ($Agent -eq 'vscode') {
        Install-PluginSkillsTo -TargetRoot (Join-Path $env:USERPROFILE '.copilot\skills')
        if ($Workspace) {
            Push-Location $Workspace
            try { Invoke-Tool $graphify @('vscode', 'install') } finally { Pop-Location }
        } else {
            Write-Step 'VS Code project adapter skipped; rerun with -Workspace to write .github/copilot-instructions.md.'
        }
        return
    }
    switch ($Agent) {
        'claude'  { Invoke-Tool $graphify @('install', '--platform', 'windows') }
        default   { Invoke-Tool $graphify @('install', '--platform', $Agent) }
    }
}

function Install-AntigravityPluginSkills {
    $targetRoot = Join-Path $env:USERPROFILE '.gemini\config\skills'
    Install-PluginSkillsTo -TargetRoot $targetRoot
}

function Install-PluginSkillsTo {
    param([string]$TargetRoot)
    $sourceRoot = Join-Path (Split-Path -Parent $scriptDir) 'skills'
    if ($DryRun) {
        Write-Step "copy plugin skills to $TargetRoot"
        return
    }
    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
    foreach ($name in @('gbrain-graphify-setup', 'project-knowledge-bootstrap', 'gbrain-graphify-doctor')) {
        Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination $TargetRoot -Recurse -Force
    }
    Write-Step "Plugin skills installed to $TargetRoot"
}

function Test-CommandShape([object]$Entry, [string]$Name, [string]$ExpectedCommand) {
    if (-not $Entry) { return $true }
    $transport = $Entry.transport
    if (-not $transport) { return $false }
    $command = [string]$transport.command
    $args = @($transport.args)
    if ([string]$transport.type -ne 'stdio' -or -not $command -or
        [IO.Path]::GetFullPath($command) -ne [IO.Path]::GetFullPath($ExpectedCommand)) {
        return $false
    }
    if ($Name -eq 'gbrain') {
        return $args.Count -eq 1 -and $args[0] -eq 'serve'
    }
    return $args.Count -eq 0
}

function Assert-FileMcpConfig([string]$Platform, [string]$ConfigPath) {
    if (-not (Test-Path -LiteralPath $ConfigPath)) { return }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python 3.10+ is required to validate existing $Platform MCP configuration at $ConfigPath"
    }
    $platformKey = $Platform.ToLowerInvariant()
    $arguments = @(
        (Get-FileHostHelper $platformKey)
    )
    if ($platformKey -ne 'antigravity') {
        $arguments += @('--platform', (Get-FileHostPlatform $platformKey))
    }
    $gbrainExpected = if (Get-Command gbrain -ErrorAction SilentlyContinue) { Get-GBrainPath } else { 'gbrain' }
    $graphifyExpected = if (Get-Command graphify-mcp -ErrorAction SilentlyContinue) { Resolve-ToolPath 'graphify-mcp' } else { 'graphify-mcp' }
    $arguments += @(
        '--config', $ConfigPath,
        '--gbrain-command', $gbrainExpected,
        '--graphify-command', $graphifyExpected,
        '--validate-only'
    )
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $raw = & $python.Source @arguments 2>$null
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -in @(0, 2)) {
        $report = ($raw -join "`n") | ConvertFrom-Json
        if ($Platform -eq 'Claude') {
            $script:ClaudeConfigPresent = @($report.present)
            $script:ClaudeConfigConflicts = @($report.conflicts)
        }
    }
    if ($exitCode -eq 0) { return }
    if ($exitCode -eq 2 -and $ReplaceConflicts) {
        return
    }
    if ($exitCode -eq 2) {
        throw "$Platform MCP configuration conflicts with the requested stdio configuration. Rerun with -ReplaceConflicts after review."
    }
    throw "$Platform MCP configuration is invalid and was not modified: $ConfigPath"
}

function Get-ObjectPropertyValue([object]$Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Assert-AntigravityConfig([string]$ConfigPath) {
    if (-not (Test-Path -LiteralPath $ConfigPath)) { return }
    try {
        $config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
    } catch {
        throw "Antigravity MCP configuration is invalid and was not modified: $ConfigPath"
    }
    $servers = Get-ObjectPropertyValue $config 'mcpServers'
    if ($null -eq $servers) { return }
    if ($servers -isnot [PSCustomObject]) {
        throw "Antigravity MCP configuration is invalid and was not modified: $ConfigPath"
    }
    foreach ($name in @('gbrain', 'graphify')) {
        $entry = Get-ObjectPropertyValue $servers $name
        if (-not $entry) { continue }
        $expected = if ($name -eq 'gbrain') { Get-GBrainPath } else { Resolve-ToolPath 'graphify-mcp' }
        $args = @(Get-ObjectPropertyValue $entry 'args')
        [string[]]$expectedArgs = if ($name -eq 'gbrain') { @('serve') } else { @() }
        $sameArgs = ($args.Count -eq $expectedArgs.Count) -and
            (($args -join [char]0) -ceq ($expectedArgs -join [char]0))
        $command = [string](Get-ObjectPropertyValue $entry 'command')
        $type = [string](Get-ObjectPropertyValue $entry 'type')
        $disabled = Get-ObjectPropertyValue $entry 'disabled'
        $valid = $type -eq 'stdio' -and $command -and
            [IO.Path]::GetFullPath($command) -eq [IO.Path]::GetFullPath($expected) -and
            $sameArgs -and $disabled -ne $true
        if (-not $valid -and -not $ReplaceConflicts) {
            throw "Antigravity MCP entry '$name' conflicts with the requested stdio configuration. Rerun with -ReplaceConflicts after review."
        }
    }
}

function Assert-NoHostConflicts {
    foreach ($agent in $requestedAgents) {
        if ($agent -eq 'codex') {
            foreach ($name in @('gbrain', 'graphify')) {
                $entry = Get-CodexServer $name
                $expected = if ($name -eq 'gbrain') { Get-GBrainPath } else { Resolve-ToolPath 'graphify-mcp' }
                if ($entry -and -not (Test-CommandShape $entry $name $expected) -and -not $ReplaceConflicts) {
                    throw "Codex MCP entry '$name' conflicts with the requested stdio configuration. Rerun with -ReplaceConflicts after review."
                }
            }
        } elseif ($agent -eq 'claude') {
            $hasClaudeEntries = (Test-ClaudeServerExists 'gbrain') -or (Test-ClaudeServerExists 'graphify')
            if ($hasClaudeEntries) {
                Assert-FileMcpConfig 'Claude' (Join-Path $env:USERPROFILE '.claude.json')
            }
        } elseif ($agent -eq 'antigravity') {
            $configPath = Join-Path $env:USERPROFILE '.gemini\antigravity\mcp_config.json'
            Assert-AntigravityConfig $configPath
        } elseif ($agent -in @('workbuddy', 'cursor', 'vscode')) {
            Assert-FileMcpConfig $agent (Get-HostConfigPath $agent)
        }
    }
}

function Assert-HostCommands {
    if ($DryRun) { return }
    foreach ($agent in $requestedAgents) {
        if ($agent -in @('codex', 'claude') -and -not (Get-Command $agent -ErrorAction SilentlyContinue)) {
            throw "$agent command not found"
        }
    }
}

Write-Step 'Phase 1/3: preflight'
if (-not $DryRun) { Refresh-UserPath }
Assert-HostCommands
Assert-NoHostConflicts
Assert-PinnedVersions

Write-Step 'Phase 2/3: apply'
Ensure-PinnedTools
Ensure-GBrainInit

$gbrainPath = Get-GBrainPath
$graphifyMcp = Resolve-ToolPath 'graphify-mcp'

foreach ($agent in $requestedAgents) {
    Install-GraphifyAdapter $agent
    if ($agent -eq 'codex') {
        Ensure-CodexMcp 'gbrain' $gbrainPath @('serve')
        Ensure-CodexMcp 'graphify' $graphifyMcp @()
    } elseif ($agent -eq 'claude') {
        Ensure-ClaudeMcp 'gbrain' $gbrainPath @('serve')
        Ensure-ClaudeMcp 'graphify' $graphifyMcp @()
    } elseif ($agent -eq 'antigravity') {
        Install-AntigravityPluginSkills
        $arguments = @(
            (Join-Path $scriptDir 'configure_antigravity.py'),
            '--gbrain-command', $gbrainPath,
            '--graphify-command', $graphifyMcp
        )
        if ($ReplaceConflicts) { $arguments += '--replace-conflicts' }
        if ($DryRun) { $arguments += '--dry-run' }
        Invoke-Tool (Resolve-ToolPath 'python') $arguments
    } elseif ($agent -in @('workbuddy', 'cursor', 'vscode')) {
        Configure-FileMcp $agent (Get-HostConfigPath $agent) $gbrainPath $graphifyMcp
    }
}

Write-Step 'Phase 3/3: verify'
if (-not $DryRun) {
    $doctorArgs = @(
        (Join-Path $scriptDir 'doctor.py'), '--agents', ($requestedAgents -join ',')
    )
    if ($Workspace) { $doctorArgs += @('--workspace', $Workspace) }
    Invoke-Tool (Resolve-ToolPath 'python') $doctorArgs
}

if ($DryRun) {
    Write-Step 'Dry-run complete; no changes were applied.'
} else {
    Write-Step 'ok: true'
    Write-Step 'Restart the Agent session to load the gbrain and graphify MCP tools.'
}
