<#
.SYNOPSIS
  OpenAgent developer bootstrap (cross-platform PowerShell).
.DESCRIPTION
  Clone -> setup -> doctor -> develop. Idempotent, per-user, no admin.
  Usage: powershell -ExecutionPolicy Bypass -File setup.ps1 [-Offline] [-Minimal] [-Yes]
#>
[CmdletBinding()]
param(
  [switch]$Offline,
  [switch]$Minimal,
  [switch]$Yes,
  [switch]$SkipModel
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Step([string]$m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok([string]$m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  [!!] $m" -ForegroundColor Yellow }

try {
  # 1-2. OS + arch
  Step "Detecting OS"
  $os = if ($IsWindows -or $env:OS -like "*Windows*") { "Windows" } else { $PSVersionTable.OS }
  Ok "$os ($([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture))"

  # 3. Node
  Step "Detecting Node"
  $node = Get-Command node -ErrorAction SilentlyContinue
  if (-not $node) { throw "Node.js 20+ is required: https://nodejs.org/en/download" }
  $major = (& node -e "console.log(process.versions.node.split('.')[0])").Trim()
  if ([int]$major -lt 20) { throw "Node.js 20+ is required (found v$major)" }
  Ok "Node $(& node -v)"

  # 4. Git
  Step "Detecting Git"
  if (Get-Command git -ErrorAction SilentlyContinue) { Ok "$(git --version)" }
  else { Warn "Git not found - continuing without Git integration (https://git-scm.com/downloads)" }

  # 5. Package manager
  Step "Detecting package manager"
  $pkg = "pnpm"
  if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Warn "pnpm not found - trying corepack"
    if (Get-Command corepack -ErrorAction SilentlyContinue) {
      & corepack enable 2>$null; & corepack prepare pnpm@8.15.0 --activate 2>$null
    }
  }
  if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { $pkg = "npm"; Warn "using npm fallback" }
  else { Ok "pnpm $(pnpm --version)" }

  # 6-9. Hardware
  Step "Detecting hardware"
  $ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue).TotalPhysicalMemory / 1GB, 1)
  if ($ramGb) { Ok "$ramGb GB RAM" } else { Ok "hardware probe via openagent setup" }

  # 10. Local directories (per-user)
  Step "Creating local directories"
  $dataDir = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "OpenAgent\data" } else { Join-Path $HOME ".local/share/openagent/data" }
  New-Item -ItemType Directory -Force -Path @("$dataDir/workspace", "$dataDir/logs") | Out-Null
  Ok $dataDir

  # 11. Dependencies
  Step "Installing dependencies"
  if ($pkg -eq "pnpm") { & pnpm install } else { & npm install --no-audit --no-fund }
  Ok "dependencies installed"

  # 12. Build CLI
  Step "Building CLI"
  if ($pkg -eq "pnpm") { & pnpm --filter @openagent/cli build } else { & npm --prefix packages/cli run build }
  Ok "CLI built"

  # 13-14. Environment (never overwrite .env)
  Step "Configuring environment"
  if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") { & node scripts/setup.mjs --yes; Ok ".env created" }
    else { Warn ".env.example missing - skipping" }
  } else { Ok ".env already exists - untouched" }

  # 15-17. Zero-config setup via real CLI
  Step "Running openagent setup"
  $args = @("setup", "--yes")
  if ($Offline) { $args += "--offline" }
  if ($Minimal -or $Yes) { $args += "--minimal" }
  if ($SkipModel) { $args += "--skip-model" }
  & node packages/cli/bin/openagent.js @args
  if ($LASTEXITCODE -ne 0) { throw "'openagent setup' failed (exit $LASTEXITCODE). Repair: node packages/cli/bin/openagent.js repair" }

  # 18-19. Health + smoke
  Step "Health check"
  & node packages/cli/bin/openagent.js doctor
  & node packages/cli/bin/openagent.js --version | Out-Null
  Ok "CLI smoke test passed"

  # 22-23. Repo-local launcher (no PATH edit)
  Step "Creating dev launcher"
  '@echo off' | Set-Content -LiteralPath "openagent-dev.cmd" -Encoding Ascii
  Add-Content -LiteralPath "openagent-dev.cmd" 'node "%~dp0packages\cli\bin\openagent.js" %*'
  Ok "openagent-dev.cmd (repo-local, no PATH change)"

  Write-Host ""
  Write-Host "  OPENAGENT SETUP COMPLETE" -ForegroundColor Green
  Write-Host "  Next: .\openagent-dev.cmd doctor | .\openagent-dev.cmd start"
} catch {
  Write-Host ""
  Write-Host "  SETUP FAILED" -ForegroundColor Red
  Write-Host "  Reason: $($_.Exception.Message)"
  Write-Host "  Automatic repair: node packages/cli/bin/openagent.js repair"
  Write-Host "  Logs: $dataDir/logs (if created)"
  exit 1
}
