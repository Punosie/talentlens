<#
.SYNOPSIS
  One-click update, started by TalentLens itself (Settings never needs a terminal).
  Stops the server, pulls the new version, installs dependencies, builds the UI aside and swaps
  it in, then starts TalentLens again. On any failure the code goes back to the previous commit
  and the previous version is started again, so the user is never left without a working app.
  Progress is written to -StatusFile as JSON for the app to show.
#>
param(
    [int]$Port = 8765,
    [string]$StatusFile = (Join-Path $env:LOCALAPPDATA 'TalentLens\update\status.json'),
    [string]$Branch = 'main'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

$From = $null; $To = $null
try {
    $prev = Get-Content $StatusFile -Raw -ErrorAction Stop | ConvertFrom-Json
    $From = $prev.from; $To = $prev.to
} catch { }

function Set-Status([string]$State, [string]$Message) {
    $obj = [ordered]@{ state = $State; message = $Message; from = $From; to = $To; at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') }
    $dir = Split-Path -Parent $StatusFile
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    [IO.File]::WriteAllText($StatusFile, ($obj | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] $State - $Message"
}

function Run([string]$What, [scriptblock]$Block) {
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

function Test-PortFree {
    return -not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

$old = $null
try {
    Set-Status 'updating' 'Stopping TalentLens'
    Start-Sleep -Seconds 1   # let the "update started" reply reach the browser
    & (Join-Path $PSScriptRoot 'stop.ps1') | Out-Null
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Test-PortFree)) {
        if ((Get-Date) -gt $deadline) { throw 'TalentLens did not stop' }
        Start-Sleep -Milliseconds 500
    }

    $old = (git rev-parse HEAD).Trim()
    Set-Status 'updating' 'Downloading the new version'
    Run 'git fetch' { git fetch --quiet origin $Branch }
    Run 'git merge' { git merge --ff-only "origin/$Branch" }

    Set-Status 'updating' 'Installing components'
    Run 'uv sync' { uv sync --frozen }

    Set-Status 'updating' 'Building the screens'
    Push-Location (Join-Path $Root 'frontend')
    try {
        Run 'npm ci' { npm ci --no-audit --no-fund }
        if (Test-Path 'dist-next') { Remove-Item -Recurse -Force 'dist-next' }
        Run 'npm run build' { npm run build -- --outDir dist-next --emptyOutDir }
        if (-not (Test-Path 'dist-next\index.html')) { throw 'The new screens were not built' }
        if (Test-Path 'dist-old') { Remove-Item -Recurse -Force 'dist-old' }
        if (Test-Path 'dist') { Rename-Item 'dist' 'dist-old' }
        Rename-Item 'dist-next' 'dist'
        if (Test-Path 'dist-old') { Remove-Item -Recurse -Force 'dist-old' -ErrorAction SilentlyContinue }
    } finally { Pop-Location }

    Set-Status 'done' "Updated to $To"
} catch {
    $msg = $_.Exception.Message
    Write-Host "Update failed: $msg"
    try {
        if ($old -and ((git rev-parse HEAD).Trim() -ne $old)) {
            git reset --keep $old | Out-Null    # back to the version that worked (local edits kept)
            uv sync --frozen | Out-Null
        }
    } catch { Write-Host "Rollback problem: $($_.Exception.Message)" }
    Set-Status 'failed' $msg
} finally {
    # always bring TalentLens back, on the new version or the previous one
    & (Join-Path $PSScriptRoot 'start.ps1') -NoBrowser
}
