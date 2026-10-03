<#
.SYNOPSIS
  Uninstall OpenAgent (application only by default; user data is preserved).

.DESCRIPTION
  Stops the engine, removes shortcuts, autostart, file association and the
  Uninstall entry, and deletes application binaries. User data
  (%LOCALAPPDATA%\OpenAgent\data) is kept unless -Full is passed, in which
  case explicit confirmation is required.

.PARAMETER Full
  Also delete user data (workflows, agents, memory, settings).

.PARAMETER Confirm
  Skip the confirmation prompt for -Full.
#>
[CmdletBinding()]
param(
  [switch]$Full,
  [switch]$Confirm
)

$ErrorActionPreference = "Continue"
$AppDir = Join-Path $env:LOCALAPPDATA "OpenAgent"
$DataDir = Join-Path $AppDir "data"
$Shim = Join-Path $AppDir "bin\openagent.cmd"

Write-Host "Uninstall OpenAgent"

# Stop the engine (PID file first, process sweep as fallback).
try {
  $pidFile = Join-Path $DataDir "workspace\.openagent\openagent.pid"
  if (Test-Path $pidFile) {
    $rec = Get-Content $pidFile -Raw | ConvertFrom-Json
    Stop-Process -Id $rec.pid -Force -ErrorAction SilentlyContinue
  }
} catch { }
Get-Process | Where-Object { $_.Path -like "$AppDir*" -or ($_.CommandLine -like "*openagent*" -and $_.Name -eq "node") } -ErrorAction SilentlyContinue |
  Stop-Process -Force -ErrorAction SilentlyContinue

if ($Full -and -not $Confirm) {
  $ans = Read-Host "Delete ALL user data in $DataDir (workflows, memory, settings)? [y/N]"
  if ($ans -notin @("y", "Y", "yes")) { Write-Host "Cancelled - nothing removed."; exit 0 }
}

# Shortcuts.
$startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "OpenAgent"
Remove-Item -Recurse -Force $startMenu -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path ([Environment]::GetFolderPath("Desktop")) "OpenAgent.lnk") -ErrorAction SilentlyContinue

# Registry (HKCU only - never touches machine hives).
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "OpenAgent" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenAgent" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "HKCU:\Software\Classes\OpenAgent.Workflow" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "HKCU:\Software\Classes\.openagent-workflow.json" -ErrorAction SilentlyContinue

# User PATH entry.
try {
  $p = [Environment]::GetEnvironmentVariable("Path", "User")
  if ($null -eq $p) { $p = "" }
  $bin = Join-Path $AppDir "bin"
  $parts = $p -split ";" | Where-Object { $_ -ne "" -and $_ -ne $bin }
  [Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")
} catch { }

if ($Full) {
  Remove-Item -Recurse -Force $AppDir -ErrorAction SilentlyContinue
  Write-Host "Removed application + user data."
} else {
  # Application only - data/ stays.
  foreach ($sub in @("app", "runtime", "engine", "browser", "models", "plugins", "bin", "cache")) {
    Remove-Item -Recurse -Force (Join-Path $AppDir $sub) -ErrorAction SilentlyContinue
  }
  Write-Host "Removed application only. User data preserved in $DataDir."
}
