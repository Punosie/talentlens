<#
.SYNOPSIS
  Uninstall TalentLens from this Windows PC, and optionally Ollama and the tools setup installed.

.DESCRIPTION
  Your resume folders (CVs, JDs) and every file in them are NEVER touched.

  Always removed (TalentLens itself):
    - the running server, the Desktop and Start menu shortcuts
    - %LOCALAPPDATA%\TalentLens  (library databases, settings, AI search models, logs, icons)
  Asked one by one (or all at once with -All):
    - Ollama and its downloaded AI models (%USERPROFILE%\.ollama)
    - the Playwright test browser (%LOCALAPPDATA%\ms-playwright)
    - Graphify (developer tool) and uv-managed Python + caches
    - uv, Node.js, Git, GitHub CLI   (shared tools: other programs may use them)
    - LibreOffice
    - the TalentLens code folder itself

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1             # asks before each extra
  powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1 -DryRun     # only shows what it would do
  powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1 -All -Yes   # remove everything, no questions
#>
param(
    [switch]$All,       # include every optional component
    [switch]$Yes,       # don't ask; use with -All to remove everything unattended
    [switch]$KeepData,  # keep %LOCALAPPDATA%\TalentLens (libraries, settings) for a later reinstall
    [switch]$DryRun     # print what would happen, change nothing
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $env:LOCALAPPDATA 'TalentLens'
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Info([string]$Text) { Write-Host "    $Text" }
function Done([string]$Text) { Write-Host "    $Text" -ForegroundColor Green }
function Have([string]$Cmd) { return [bool](Get-Command $Cmd -ErrorAction SilentlyContinue) }

function Confirm([string]$Question, [bool]$Default = $false) {
    if ($All) { return $true }
    if ($Yes) { return $Default }
    $hint = if ($Default) { '[Y/n]' } else { '[y/N]' }
    $a = Read-Host "    $Question $hint"
    if ([string]::IsNullOrWhiteSpace($a)) { return $Default }
    return $a.Trim().ToLower().StartsWith('y')
}

function Run([string]$What, [scriptblock]$Action) {
    if ($DryRun) { Info "[dry run] would: $What"; return }
    try { & $Action; Done $What } catch { Write-Host "    could not $($What): $($_.Exception.Message)" -ForegroundColor Yellow }
}

function Remove-Dir([string]$Path, [string]$Label) {
    if (-not (Test-Path $Path)) { Info "$Label not found (already removed)"; return }
    $size = (Get-ChildItem $Path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    Run ("remove $Label ($Path, {0:N0} MB)" -f ($size / 1MB)) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

function Winget-Remove([string]$Id, [string]$Name) {
    if (-not (Have 'winget')) { Info "winget not available; uninstall $Name from Settings > Apps"; return }
    $listed = winget list --id $Id -e --disable-interactivity 2>$null | Out-String
    if ($listed -notmatch [regex]::Escape($Id)) { Info "$Name is not installed via winget (skipped)"; return }
    Run "uninstall $Name" { winget uninstall --id $Id -e --silent --disable-interactivity | Out-Null }
}

# --- remember where the resumes are, so we can reassure (and never touch them) ------------
$resumeDirs = @()
$settingsFile = Join-Path $DataDir 'settings.json'
if (Test-Path $settingsFile) {
    try { $s = Get-Content $settingsFile -Raw | ConvertFrom-Json; if ($s.cv_dir) { $resumeDirs += $s.cv_dir } } catch {}
}
$jds = Join-Path ([Environment]::GetFolderPath('Desktop')) 'JDs'
if (Test-Path $jds) { $resumeDirs += $jds }

Write-Host 'TalentLens uninstaller' -ForegroundColor Cyan
if ($DryRun) { Write-Host '(dry run: nothing will be changed)' -ForegroundColor Yellow }
Info 'Your resume folders and their files are never touched.'

# --- 1. TalentLens itself -----------------------------------------------------------
Step 'Stopping TalentLens'
$port = 8765
$envFile = Join-Path $Root '.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) { if ($line -match '^\s*TALENTLENS_PORT\s*=\s*(\d+)') { $port = [int]$Matches[1] } }
}
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($procId in ($conns.OwningProcess | Sort-Object -Unique)) { Run "stop the TalentLens server (PID $procId)" { Stop-Process -Id $procId -Force } }
} else { Info 'not running' }

Step 'Removing shortcuts'
foreach ($lnk in @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'TalentLens.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'TalentLens.lnk'))) {
    if (Test-Path $lnk) { Run "remove $lnk" { Remove-Item -LiteralPath $lnk -Force } } else { Info "$lnk not found" }
}

Step 'Removing TalentLens working data'
if ($KeepData) { Info "kept $DataDir (-KeepData)" }
elseif ((Split-Path $DataDir -Leaf) -ne 'TalentLens') { Info "unexpected data path $DataDir; not removed" }
else { Remove-Dir $DataDir 'library databases, settings, AI search models and logs' }

# --- 2. optional components ---------------------------------------------------------------
Step 'Ollama (local AI) and its models'
$ollamaModels = Join-Path $env:USERPROFILE '.ollama'
if ((Have 'ollama') -or (Test-Path "$env:LOCALAPPDATA\Programs\Ollama") -or (Test-Path $ollamaModels)) {
    if (Confirm 'Remove Ollama and all its downloaded AI models? (other apps may use Ollama)') {
        Get-Process 'ollama', 'ollama app' -ErrorAction SilentlyContinue | ForEach-Object { Run "stop $($_.ProcessName)" { Stop-Process -Id $_.Id -Force } }
        Winget-Remove 'Ollama.Ollama' 'Ollama'
        Remove-Dir $ollamaModels 'Ollama models'
    } else { Info 'kept' }
} else { Info 'not installed' }

Step 'Test browser (Playwright Chromium)'
$pw = Join-Path $env:LOCALAPPDATA 'ms-playwright'
if (Test-Path $pw) {
    if (Confirm 'Remove the Playwright test browsers? (shared with other projects that use Playwright)' $true) { Remove-Dir $pw 'Playwright browsers' } else { Info 'kept' }
} else { Info 'not installed' }

Step 'Graphify and uv-managed Python'
if (Confirm 'Remove Graphify, uv-managed Python versions and uv caches?') {
    $graphify = Join-Path $env:USERPROFILE '.local\bin\graphify.exe'
    if (Test-Path $graphify) { Run 'unregister Graphify from Claude Code' { & $graphify uninstall | Out-Null } }
    if (Have 'uv') {
        Run 'uninstall Graphify' { uv tool uninstall graphifyy 2>$null | Out-Null }
        Run 'remove uv-managed Python versions' { uv python uninstall --all 2>$null | Out-Null }
        Run 'clean the uv cache' { uv cache clean 2>$null | Out-Null }
    }
} else { Info 'kept' }

Step 'Shared developer tools (uv, Node.js, Git, GitHub CLI)'
Info 'Other programs may need these. Only remove them if you installed them just for TalentLens.'
foreach ($t in @(
        @('astral-sh.uv', 'uv'),
        @('OpenJS.NodeJS.LTS', 'Node.js LTS'),
        @('GitHub.cli', 'GitHub CLI'),
        @('Git.Git', 'Git'))) {
    if (Confirm "Uninstall $($t[1])?") { Winget-Remove $t[0] $t[1] } else { Info "kept $($t[1])" }
}

Step 'LibreOffice'
if (Test-Path 'C:\Program Files\LibreOffice\program\soffice.exe') {
    if (Confirm 'Uninstall LibreOffice?') { Winget-Remove 'TheDocumentFoundation.LibreOffice' 'LibreOffice' } else { Info 'kept' }
} else { Info 'not installed' }

Step 'TalentLens code folder'
if (Confirm "Delete the TalentLens code folder ($Root)?") {
    if ($DryRun) { Info "[dry run] would: delete $Root after this script exits" }
    else {
        # can't delete the folder this script runs from: delete it from a separate process
        $cmd = "/c timeout /t 3 /nobreak >nul & rmdir /s /q `"$Root`""
        Start-Process -FilePath 'cmd.exe' -ArgumentList $cmd -WindowStyle Hidden
        Done "will delete $Root in a few seconds"
    }
} else { Info "kept $Root" }

Write-Host ''
Write-Host ($(if ($DryRun) { 'Dry run finished. Nothing was changed.' } else { 'TalentLens has been uninstalled.' })) -ForegroundColor Green
foreach ($d in $resumeDirs) { Info "Your files are untouched: $d" }
