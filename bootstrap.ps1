[CmdletBinding()]
param(
    [ValidateSet('auto', 'codex', 'claude', 'antigravity', 'workbuddy', 'cursor', 'vscode')]
    [string]$Agent = 'auto',
    [string]$Workspace,
    [switch]$Upgrade,
    [switch]$ReplaceConflicts,
    [switch]$UseMirrorCN,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$marketplaceName = 'gbrain-graphify-guides'
$pluginId = "gbrain-graphify@$marketplaceName"

function Write-Step([string]$Message) {
    Write-Output "[gbrain-graphify-bootstrap] $Message"
}

function Invoke-Checked([string]$File, [string[]]$Arguments) {
    Write-Step ("{0} {1}" -f $File, ($Arguments -join ' '))
    if ($DryRun) { return }
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File exited with code $LASTEXITCODE" }
}

function Resolve-HostCommand([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    if ($DryRun) { return $Name }
    throw "$Name command not found"
}

function Resolve-Agent {
    if ($Agent -ne 'auto') { return $Agent }
    $candidates = @()
    if (Get-Command codex -ErrorAction SilentlyContinue) { $candidates += 'codex' }
    if (Get-Command claude -ErrorAction SilentlyContinue) { $candidates += 'claude' }
    if (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.gemini\antigravity')) { $candidates += 'antigravity' }
    if ((Get-Command workbuddy -ErrorAction SilentlyContinue) -or
        (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.workbuddy'))) { $candidates += 'workbuddy' }
    if ((Get-Command cursor -ErrorAction SilentlyContinue) -or
        (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.cursor'))) { $candidates += 'cursor' }
    $appData = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $env:USERPROFILE 'AppData\Roaming' }
    $vscodeConfig = Join-Path $appData 'Code\User\mcp.json'
    if ((Get-Command code -ErrorAction SilentlyContinue) -or
        (Get-Command code-insiders -ErrorAction SilentlyContinue) -or
        (Test-Path -LiteralPath $vscodeConfig)) { $candidates += 'vscode' }
    $candidates = @($candidates | Select-Object -Unique)
    if ($candidates.Count -eq 1) { return $candidates[0] }
    if ($candidates.Count -eq 0) {
        throw 'Could not detect a supported agent; rerun with -Agent codex, claude, antigravity, workbuddy, cursor, or vscode.'
    }
    throw "Multiple supported agents detected ($($candidates -join ', ')); rerun with an explicit -Agent."
}

$Agent = Resolve-Agent
if ($Workspace) {
    $Workspace = [IO.Path]::GetFullPath($Workspace)
    if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
        throw "Workspace does not exist: $Workspace"
    }
}

function Register-CodexPlugin {
    $codex = Resolve-HostCommand 'codex'
    if ($DryRun -and -not (Get-Command codex -ErrorAction SilentlyContinue)) {
        Invoke-Checked $codex @('plugin', 'marketplace', 'add', $repoRoot)
        Invoke-Checked $codex @('plugin', 'add', $pluginId)
        return
    }

    $marketplaces = (& $codex plugin marketplace list --json | ConvertFrom-Json).marketplaces
    $existingMarketplace = $marketplaces | Where-Object { $_.name -eq $marketplaceName }
    if ($existingMarketplace) {
        $existingRoot = [IO.Path]::GetFullPath([string]$existingMarketplace.root)
        if ($existingRoot -ne [IO.Path]::GetFullPath($repoRoot)) {
            throw "Codex marketplace '$marketplaceName' already points to $existingRoot"
        }
        Write-Step "Codex marketplace already registered from this checkout"
    } else {
        Invoke-Checked $codex @('plugin', 'marketplace', 'add', $repoRoot)
    }

    $installed = (& $codex plugin list --json | ConvertFrom-Json).installed
    if ($installed.pluginId -contains $pluginId) {
        if ($Upgrade) {
            Invoke-Checked $codex @('plugin', 'remove', $pluginId)
            Invoke-Checked $codex @('plugin', 'add', $pluginId)
        } else {
            Write-Step "Codex plugin already installed"
        }
    } else {
        Invoke-Checked $codex @('plugin', 'add', $pluginId)
    }
}

function Register-ClaudePlugin {
    $claude = Resolve-HostCommand 'claude'
    if ($DryRun -and -not (Get-Command claude -ErrorAction SilentlyContinue)) {
        Invoke-Checked $claude @('plugin', 'marketplace', 'add', $repoRoot, '--scope', 'user')
        Invoke-Checked $claude @('plugin', 'install', $pluginId, '--scope', 'user')
        return
    }

    $marketplaces = & $claude plugin marketplace list --json | ConvertFrom-Json
    $existingMarketplace = $marketplaces | Where-Object { $_.name -eq $marketplaceName }
    if ($existingMarketplace) {
        $existingPath = [string]$existingMarketplace.path
        if (-not $existingPath) { $existingPath = [string]$existingMarketplace.installLocation }
        if ($existingMarketplace.source -eq 'directory' -and
            [IO.Path]::GetFullPath($existingPath) -ne [IO.Path]::GetFullPath($repoRoot)) {
            throw "Claude marketplace '$marketplaceName' already points to $existingPath"
        }
        Write-Step "Claude marketplace already registered"
        if ($Upgrade) {
            Invoke-Checked $claude @('plugin', 'marketplace', 'update', $marketplaceName)
        }
    } else {
        Invoke-Checked $claude @('plugin', 'marketplace', 'add', $repoRoot, '--scope', 'user')
    }

    $installed = & $claude plugin list --json | ConvertFrom-Json
    if ($installed.id -contains $pluginId) {
        if ($Upgrade) {
            Invoke-Checked $claude @('plugin', 'update', $pluginId, '--scope', 'user')
        } else {
            Write-Step "Claude plugin already installed"
        }
    } else {
        Invoke-Checked $claude @('plugin', 'install', $pluginId, '--scope', 'user')
    }
}

switch ($Agent) {
    'codex' { Register-CodexPlugin }
    'claude' { Register-ClaudePlugin }
    'antigravity' { Write-Step 'Antigravity skills will be installed by setup' }
}

$setupParams = @{
    Agents = @($Agent)
    Upgrade = $Upgrade
    ReplaceConflicts = $ReplaceConflicts
    UseMirrorCN = $UseMirrorCN
    DryRun = $DryRun
}
if ($Workspace) { $setupParams.Workspace = $Workspace }

$setup = Join-Path $repoRoot 'plugins\gbrain-graphify\scripts\setup.ps1'
Write-Step "Running setup for $Agent"
& $setup @setupParams
