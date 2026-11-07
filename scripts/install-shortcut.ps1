<#
.SYNOPSIS
  Create a "TalentLens" shortcut on the Desktop (and optionally in the Start menu)
  that starts the app and opens it in the browser.
#>
param([switch]$StartMenu)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$start = Join-Path $Root 'scripts\start.ps1'
$icon = Join-Path $Root 'assets\talentlens.ico'
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

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
