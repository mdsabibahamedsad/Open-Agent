<#
.SYNOPSIS
  One-click per-user installer for OpenAgent (no admin required).

.DESCRIPTION
  Installs OpenAgent into %LOCALAPPDATA%\OpenAgent with its own layout,
  wires Start Menu / Desktop shortcuts, an `openagent` shim, autostart,
  an Uninstall entry and workflow file association, then runs the
  zero-config setup (`openagent setup --yes`) and starts the engine.

  Never touches global Node.js, PATH (except an appended user entry),
  Docker, or databases. User data lives in <app>\data and is preserved
  across updates and uninstalls (unless -Full is used on uninstall).

.PARAMETER Source
  Local .zip payload (portable app files) or an https:// URL to download.
  Defaults to the latest GitHub release bundle.

.PARAMETER Offline
  Skip every step that needs the internet.

.PARAMETER SkipModel
  Skip the AI model download (can be completed later from the dashboard).

.PARAMETER NoShortcut
  Skip the desktop shortcut.

.PARAMETER NoStartup
  Do not register OpenAgent to start with Windows.

.PARAMETER Silent
  Non-interactive (used by the NSIS wrapper).
#>
[CmdletBinding()]
param(
  [string]$Source = "",
  [switch]$Offline,
  [switch]$SkipModel,
  [switch]$NoShortcut,
  [switch]$NoStartup,
  [switch]$Silent
)

$ErrorActionPreference = "Stop"

$AppName = "OpenAgent"
$AppDir = Join-Path $env:LOCALAPPDATA "OpenAgent"
$DataDir = Join-Path $AppDir "data"
$BinDir = Join-Path $AppDir "bin"
$Shim = Join-Path $BinDir "openagent.cmd"

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-WarnMsg([string]$msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }

# ---------- 1. System check ----------
Write-Step "System check"
$os = Get-CimInstance Win32_OperatingSystem
$ramGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$arch = $env:PROCESSOR_ARCHITECTURE
Write-Ok "Windows $($os.Caption) ($arch)"
if ($ramGb -ge 8) { Write-Ok "$ramGb GB RAM" } else { Write-WarnMsg "$ramGb GB RAM - lightweight mode will be used" }
$disk = Get-PSDrive -Name ($AppDir.Substring(0, 1)) -ErrorAction SilentlyContinue
if ($disk -and ($disk.Free / 1GB) -lt 2) { Write-WarnMsg "Low disk space - installation continues anyway" }
else { Write-Ok "Storage ready" }
$online = Test-Connection -ComputerName "8.8.8.8" -Count 1 -Quiet -ErrorAction SilentlyContinue
if (-not $online) {
  try { (Invoke-WebRequest -Uri "https://registry.npmjs.org/" -Method Head -TimeoutSec 8 -UseBasicParsing).StatusCode | Out-Null; $online = $true } catch { $online = $false }
}
if ($online) { Write-Ok "Internet available" } else { Write-WarnMsg "Offline - installing available components only" }

# ---------- 2. Stage application files ----------
Write-Step "Install core"
New-Item -ItemType Directory -Force -Path @($AppDir, $DataDir, $BinDir) | Out-Null

$payload = $null
if ($Source -ne "") {
  if ($Source -match "^https?://") {
    if ($Offline) { throw "Offline mode cannot download $Source" }
    $payload = Join-Path $env:TEMP "openagent-payload.zip"
    Write-Host "  Downloading payload..."
    Invoke-WebRequest -Uri $Source -OutFile $payload -UseBasicParsing
  } elseif (Test-Path $Source) {
    $payload = $Source
  } else { throw "Source not found: $Source" }
} else {
  # Default: latest release bundle (models excluded - downloaded separately).
  $release = "https://github.com/mdsabibahamedsad/Open-Agent/releases/latest/download/openagent-win-x64.zip"
  $payload = Join-Path $env:TEMP "openagent-payload.zip"
  if (-not $Offline) {
    Write-Host "  Downloading OpenAgent release..."
    try { Invoke-WebRequest -Uri $release -OutFile $payload -UseBasicParsing }
    catch { Write-WarnMsg "Release download failed ($($_.Exception.Message)) - continuing with local files if present"; $payload = $null }
  }
}

if ($payload -and (Test-Path $payload)) {
  $sha = $payload + ".sha256"
  if (Test-Path $sha) {
    $expected = ((Get-Content $sha -Raw) -split "\s+")[0].ToLower()
    $actual = (Get-FileHash $payload -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) { throw "Checksum mismatch for payload (expected $expected, got $actual)" }
    Write-Ok "Payload checksum verified"
  }
  Write-Host "  Extracting..."
  Expand-Archive -LiteralPath $payload -DestinationPath $AppDir -Force
  Write-Ok "Application files installed"
} else {
  Write-WarnMsg "No payload staged - running in place (developer install)"
}

# ---------- 3. openagent shim (bundled runtime first, system node fallback) ----------
Write-Step "Configure command shim"
$bundledNode = Join-Path $AppDir "runtime\node\node.exe"
$cliJs = Join-Path $AppDir "app\cli\dist\bin\openagent.js"
$shimBody = "@echo off`r`n" +
  "setlocal`r`n" +
  "set OA_NODE=$bundledNode`r`n" +
  'if not exist "%OA_NODE%" where node >nul 2>nul && for /f "delims=" %i in (''where node'') do set OA_NODE=%i`' + "`r`n" +
  '"%OA_NODE%" "' + $cliJs + '" %*`r`n'
# Fallback when the payload layout is absent (running from a repo checkout):
if (-not (Test-Path $cliJs)) {
  $repoCli = Join-Path $PSScriptRoot "..\..\packages\cli\dist\bin\openagent.js"
  if (Test-Path $repoCli) { $cliJs = (Resolve-Path $repoCli).Path }
  $shimBody = "@echo off`r`n" +
    "setlocal`r`n" +
    'where node >nul 2>nul || (echo OpenAgent needs Node.js 20+ on PATH for repo installs & exit /b 1)`' + "`r`n" +
    '"node" "' + $cliJs + '" %*`r`n'
}
Set-Content -LiteralPath $Shim -Value $shimBody -Encoding Ascii
Write-Ok "openagent command ready ($Shim)"

# Append user PATH (current user only - never system-wide).
try {
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  if ($null -eq $userPath) { $userPath = "" }
  if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$BinDir", "User")
    Write-Ok "Added to user PATH (new terminals)"
  }
} catch { Write-WarnMsg "Could not update user PATH: $($_.Exception.Message)" }

# ---------- 4. Shortcuts ----------
Write-Step "Create shortcuts"
try {
  $shell = New-Object -ComObject WScript.Shell
  $startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "OpenAgent"
  New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
  $mk = {
    param($lnk, $target, $args, $desc)
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $target; $s.Arguments = $args; $s.Description = $desc
    $s.WorkingDirectory = $AppDir; $s.Save()
  }
  &$mk (Join-Path $startMenu "OpenAgent.lnk") $Shim "start" "Launch OpenAgent"
  &$mk (Join-Path $startMenu "OpenAgent Settings.lnk") $Shim "config list" "OpenAgent settings"
  &$mk (Join-Path $startMenu "OpenAgent Developer Console.lnk") "cmd.exe" "/k `"$Shim`" --help" "OpenAgent developer shell"
  &$mk (Join-Path $startMenu "OpenAgent Uninstall.lnk") "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File `"$AppDir\Uninstall-OpenAgent.ps1`"" "Uninstall OpenAgent"
  if (-not $NoShortcut) {
    &$mk (Join-Path ([Environment]::GetFolderPath("Desktop")) "OpenAgent.lnk") $Shim "start" "Launch OpenAgent"
  }
  Write-Ok "Start Menu + Desktop shortcuts created"
} catch { Write-WarnMsg "Shortcuts failed: $($_.Exception.Message)" }

# ---------- 5. Autostart / uninstall entry / file association (HKCU only) ----------
if (-not $NoStartup) {
  try {
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "OpenAgent" -Value "`"$Shim`" start --no-open" -ErrorAction Stop
    Write-Ok "Start with Windows: enabled"
  } catch { Write-WarnMsg "Autostart registration failed: $($_.Exception.Message)" }
}
try {
  $un = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenAgent"
  New-Item -Path $un -Force | Out-Null
  Set-ItemProperty -Path $un -Name "DisplayName" -Value "OpenAgent"
  Set-ItemProperty -Path $un -Name "DisplayVersion" -Value "1.0.0"
  Set-ItemProperty -Path $un -Name "Publisher" -Value "OpenAgent"
  Set-ItemProperty -Path $un -Name "InstallLocation" -Value $AppDir
  Set-ItemProperty -Path $un -Name "UninstallString" -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$AppDir\Uninstall-OpenAgent.ps1`""
  Set-ItemProperty -Path $un -Name "NoModify" -Value 1
  Write-Ok "Uninstall entry registered"
} catch { Write-WarnMsg "Uninstall entry failed: $($_.Exception.Message)" }
try {
  New-Item -Path "HKCU:\Software\Classes\OpenAgent.Workflow\shell\open\command" -Force | Out-Null
  Set-ItemProperty -Path "HKCU:\Software\Classes\OpenAgent.Workflow" -Name "(default)" -Value "OpenAgent Workflow"
  Set-ItemProperty -Path "HKCU:\Software\Classes\OpenAgent.Workflow\shell\open\command" -Name "(default)" -Value "`"$Shim`" workflow import `"%1`""
  New-Item -Path "HKCU:\Software\Classes\.openagent-workflow.json" -Force | Out-Null
  Set-ItemProperty -Path "HKCU:\Software\Classes\.openagent-workflow.json" -Name "(default)" -Value "OpenAgent.Workflow"
  Write-Ok "Workflow file association registered"
} catch { Write-WarnMsg "File association failed: $($_.Exception.Message)" }

# Copy uninstaller next to the app for the Uninstall entry.
try { Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Uninstall-OpenAgent.ps1") -Destination (Join-Path $AppDir "Uninstall-OpenAgent.ps1") -Force } catch { }

# ---------- 6. Zero-config setup + start ----------
Write-Step "Automatic configuration"
$setupArgs = @("setup", "--yes")
if ($Offline -or -not $online) { $setupArgs += "--offline" }
if ($SkipModel) { $setupArgs += "--skip-model" }
& $Shim @setupArgs
if ($LASTEXITCODE -ne 0) { throw "openagent setup failed (exit $LASTEXITCODE)" }

Write-Step "Launch"
Start-Process -FilePath $Shim -ArgumentList "start --no-open" -WorkingDirectory $AppDir
Start-Sleep -Seconds 4
$workspace = Join-Path $DataDir "workspace"
$cfg = Join-Path $workspace ".openagent\config.json"
$port = 5678
try { $port = (Get-Content $cfg -Raw | ConvertFrom-Json).server.port } catch { }
try {
  $health = Invoke-RestMethod -Uri "http://localhost:$port/health" -TimeoutSec 10
  if ($health.ok -eq $true) { Write-Ok "Engine healthy on port $port" }
} catch { Write-WarnMsg "Engine is starting - dashboard will open shortly" }
try { Start-Process "http://localhost:$port/" } catch { }

Write-Host ""
Write-Host "  You're Ready - OpenAgent is installed." -ForegroundColor Green
Write-Host "  Dashboard: http://localhost:$port/"
Write-Host "  Data (preserved on update): $DataDir"
