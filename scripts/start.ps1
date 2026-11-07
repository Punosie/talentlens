<#
.SYNOPSIS
  Start TalentLens (if it is not already running) and open it in the browser.
  Used by the desktop shortcut. Safe to run any number of times.
#>
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

# Pick up tools installed after this session started (uv, ollama)
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

function Show-Error([string]$Message) {
    try {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show($Message, 'TalentLens', 'OK', 'Error') | Out-Null
    } catch {
        Write-Error $Message
    }
}

function Get-EnvValue([string]$Name, [string]$Default) {
    $envFile = Join-Path $Root '.env'
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match "^\s*$Name\s*=\s*(.+?)\s*$") { return $Matches[1].Trim('"') }
        }
    }
    return $Default
}

$port = Get-EnvValue 'TALENTLENS_PORT' '8765'
$url = "http://127.0.0.1:$port"

function Test-Up {
    try { return (Invoke-RestMethod "$url/api/health" -TimeoutSec 2).status -eq 'ok' } catch { return $false }
}

if (-not (Test-Up)) {
    # Local LLM: start Ollama quietly if it is installed but not running (optional)
    if ((Get-EnvValue 'TALENTLENS_LLM' 'ollama') -eq 'ollama') {
        try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null } catch {
            $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
            if (-not $ollama) {
                $guess = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
                if (Test-Path $guess) { $ollama = $guess }
            }
            if ($ollama) { Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden }
        }
    }

    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) {
        Show-Error "TalentLens needs 'uv', which was not found. Run scripts\setup.ps1 first."
        exit 1
    }
    if (-not (Test-Path (Join-Path $Root 'frontend\dist\index.html'))) {
        Show-Error "The web UI has not been built yet. Run scripts\setup.ps1 first."
        exit 1
    }

    $logDir = Join-Path $env:LOCALAPPDATA 'TalentLens\logs'
    New-Item -ItemType Directory -Force $logDir | Out-Null
    Start-Process -FilePath $uv -ArgumentList @('run', '--frozen', 'talentlens') `
        -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir 'server.out.log') `
        -RedirectStandardError (Join-Path $logDir 'server.err.log')

    $deadline = (Get-Date).AddSeconds(120)
    while (-not (Test-Up)) {
        if ((Get-Date) -gt $deadline) {
            Show-Error "TalentLens did not start within 2 minutes.`nSee the logs in:`n$logDir"
            exit 1
        }
        Start-Sleep -Milliseconds 700
    }
}

if (-not $NoBrowser) { Start-Process $url }
