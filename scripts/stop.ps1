<#
.SYNOPSIS
  Stop the TalentLens server (the process listening on the TalentLens port).
  Ollama is left running because other apps may use it.
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot

$port = 8765
$envFile = Join-Path $Root '.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*TALENTLENS_PORT\s*=\s*(\d+)') { $port = [int]$Matches[1] }
    }
}

$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "TalentLens is not running (nothing listening on port $port)."
    exit 0
}
foreach ($procId in ($conns.OwningProcess | Sort-Object -Unique)) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p) {
        Write-Host "Stopping $($p.ProcessName) (PID $procId) on port $port"
        Stop-Process -Id $procId -Force
    }
}
Write-Host 'TalentLens stopped.'
