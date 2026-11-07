<#
.SYNOPSIS
  One-time (and repeatable) setup of TalentLens on a Windows laptop.

.DESCRIPTION
  Installs what is missing (uv, Node.js, Ollama), installs Python and JS dependencies,
  builds the UI, downloads the local AI models, and creates the desktop shortcut.
  Safe to run again at any time: it skips anything that is already done.
  It never modifies an existing .env file or any resume.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -CvDir "D:\Recruiting\CVs"
#>
param(
    [string]$CvDir,
    [switch]$NoAI,             # skip Ollama + LLM model (rules-only extraction)
    [switch]$SkipTests,        # skip the Playwright browser download
    [switch]$WithLibreOffice,  # install LibreOffice for .doc files (not needed if MS Word is installed)
    [switch]$NoShortcut
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Model = 'qwen2.5:3b-instruct'

function Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Ok([string]$Text) { Write-Host "    $Text" -ForegroundColor Green }
function Warn([string]$Text) { Write-Host "    $Text" -ForegroundColor Yellow }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Have([string]$Cmd) { return [bool](Get-Command $Cmd -ErrorAction SilentlyContinue) }
function Winget-Install([string]$Id, [string]$Name) {
    if (-not (Have 'winget')) { throw "winget is not available. Install '$Name' manually and re-run setup." }
    Write-Host "    Installing $Name ..."
    winget install --id $Id -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
    Refresh-Path
}
function Invoke-Native([string]$What, [scriptblock]$Block) {
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

Refresh-Path

# --- 1. tools -------------------------------------------------------------------
Step 'Checking tools'
if (-not (Have 'uv')) { Winget-Install 'astral-sh.uv' 'uv (Python manager)' }
if (-not (Have 'uv')) { throw 'uv is still not on PATH. Open a new terminal and run setup again.' }
Ok "uv $((uv --version) -replace '^uv ', '')"

if (-not (Have 'node')) { Winget-Install 'OpenJS.NodeJS.LTS' 'Node.js LTS' }
if (-not (Have 'node')) { throw 'Node.js is still not on PATH. Open a new terminal and run setup again.' }
Ok "node $(node --version)"

if (-not $NoAI) {
    $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollamaExe) {
        $guess = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (Test-Path $guess) { $ollamaExe = $guess } else {
            Winget-Install 'Ollama.Ollama' 'Ollama (local LLM runtime)'
            $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
            if (-not $ollamaExe -and (Test-Path $guess)) { $ollamaExe = $guess }
        }
    }
    if ($ollamaExe) { Ok "ollama found" } else { Warn 'Ollama not found; continuing in rules-only mode.'; $NoAI = $true }
}

if ($WithLibreOffice -and -not (Test-Path 'C:\Program Files\LibreOffice\program\soffice.exe')) {
    Winget-Install 'TheDocumentFoundation.LibreOffice' 'LibreOffice'
}

# --- 2. Python backend ------------------------------------------------------------
Step 'Installing the backend (Python 3.12 via uv)'
Invoke-Native 'uv sync' { uv sync --frozen }
Ok 'Python dependencies installed'

# --- 3. preferences (stored in the app's settings.json; .env is never written) ------
Step 'Preferences'
if ($CvDir) {
    New-Item -ItemType Directory -Force $CvDir | Out-Null
    Invoke-Native 'set-folder' { uv run --frozen talentlens set-folder "$CvDir" }
} else {
    Ok 'Resume folder: choose it in the app on first start (or it is found automatically).'
}
if ($NoAI) { Invoke-Native 'set-ai' { uv run --frozen talentlens set-ai off } }
# --- 4. web UI ----------------------------------------------------------------------
Step 'Building the web UI'
Push-Location (Join-Path $Root 'frontend')
try {
    Invoke-Native 'npm ci' { npm ci --no-audit --no-fund }
    Invoke-Native 'npm run build' { npm run build }
} finally { Pop-Location }
Ok 'UI built (frontend\dist)'

# --- 5. local AI models -------------------------------------------------------------
if (-not $NoAI) {
    Step "Downloading the local LLM ($Model, about 2 GB, first time only)"
    try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null } catch {
        Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden
        Start-Sleep -Seconds 4
    }
    Invoke-Native 'ollama pull' { & $ollamaExe pull $Model }
    Ok "$Model ready"
}
Step 'Downloading embedding, reranking and OCR models (about 300 MB, first time only)'
Invoke-Native 'model warm-up' { uv run --frozen python -m talentlens.warmup }

# --- 6. test browser (optional) ---------------------------------------------------------
if (-not $SkipTests) {
    Step 'Installing the Playwright test browser (Chromium)'
    Push-Location (Join-Path $Root 'frontend')
    try { Invoke-Native 'playwright install' { npx playwright install chromium } } finally { Pop-Location }
}

# --- 7. desktop shortcut ----------------------------------------------------------------------
if (-not $NoShortcut) {
    Step 'Creating the desktop shortcut'
    & (Join-Path $PSScriptRoot 'install-shortcut.ps1') -StartMenu
}

Write-Host "`nTalentLens is ready. Double-click 'TalentLens' on your desktop, or run scripts\start.ps1." -ForegroundColor Green
