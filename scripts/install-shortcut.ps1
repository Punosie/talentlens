<#
.SYNOPSIS
  Create a "TalentLens" shortcut on the Desktop (and optionally in the Start menu)
  that starts the app and opens it in the browser.
#>
param([switch]$StartMenu)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$start = Join-Path $Root 'scripts\start.ps1'
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

# Windows caches shortcut icons by file path, so a changed logo at the same path keeps showing
# the old picture. Copy the icon to a file named after its content: a new logo = a new path.
$srcIcon = Join-Path $Root 'assets\talentlens.ico'
$hash = (Get-FileHash -Algorithm SHA256 $srcIcon).Hash.Substring(0, 10).ToLower()
$iconDir = Join-Path $env:LOCALAPPDATA 'TalentLens\icons'
New-Item -ItemType Directory -Force $iconDir | Out-Null
$icon = Join-Path $iconDir "talentlens-$hash.ico"
if (-not (Test-Path $icon)) { Copy-Item $srcIcon $icon }
Get-ChildItem $iconDir -Filter 'talentlens-*.ico' | Where-Object { $_.FullName -ne $icon } |
    ForEach-Object { try { Remove-Item $_.FullName -Force -ErrorAction Stop } catch {} }

function New-Shortcut([string]$Path) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $ps
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$start`""
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = 'TalentLens: local resume library and JD shortlisting'
    $lnk.WindowStyle = 7  # minimized
    $lnk.Save()
    Write-Host "Shortcut created: $Path"
}

New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'TalentLens.lnk')
if ($StartMenu) {
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Programs')) 'TalentLens.lnk')
}

# Ask Explorer to refresh its icon cache (harmless if unavailable)
$ie4 = Join-Path $env:SystemRoot 'System32\ie4uinit.exe'
if (Test-Path $ie4) { Start-Process -FilePath $ie4 -ArgumentList '-show' -WindowStyle Hidden -Wait }
