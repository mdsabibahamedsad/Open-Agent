@echo off
REM OpenAgent developer bootstrap (Windows).
REM Usage: setup.cmd [--offline] [--minimal] [--yes]
REM Idempotent: safe to re-run. Never requires admin.
setlocal EnableDelayedExpansion

cd /d "%~dp0"

echo.
echo  === OpenAgent developer setup ===
echo.

REM --- 1-2. OS + architecture ---
for /f "tokens=*" %%v in ('ver') do echo  [1/12] OS: %%v
echo  [2/12] Architecture: %PROCESSOR_ARCHITECTURE%

REM --- 3. Node ---
where node >nul 2>nul
if errorlevel 1 (
  echo  [X] Node.js not found on PATH.
  echo      Install Node.js 20 LTS from https://nodejs.org/en/download
  echo      then re-run setup.cmd
  exit /b 1
)
for /f "tokens=*" %%v in ('node -v') do set NODEV=%%v
echo  [3/12] Node: %NODEV% (need v20+)
for /f "tokens=1 delims=v." %%M in ("%NODEV:.=%") do set _x=%%M
node -e "process.exit(Number(process.versions.node.split('.')[0])>=20?0:1)"
if errorlevel 1 (
  echo  [X] Node.js 20+ is required. Install it, then re-run setup.cmd
  exit /b 1
)

REM --- 4. Git (optional but recommended) ---
where git >nul 2>nul
if errorlevel 1 (
  echo  [!] Git not found - continuing without Git integration.
  echo      Optional: https://git-scm.com/downloads
) else (
  for /f "tokens=*" %%v in ('git --version') do echo  [4/12] %%v
)

REM --- 5. Package manager (pnpm preferred, corepack/npm fallback) ---
where pnpm >nul 2>nul
if errorlevel 1 (
  echo  [!] pnpm not found - trying corepack...
  where corepack >nul 2>nul
  if not errorlevel 1 (
    call corepack enable >nul 2>&1
    call corepack prepare pnpm@8.15.0 --activate >nul 2>&1
  )
)
where pnpm >nul 2>nul
if errorlevel 1 (
  echo  [!] pnpm still missing - JS dependencies will use npm as fallback.
  set PKG=npm
) else (
  for /f "tokens=*" %%v in ('pnpm --version') do echo  [5/12] pnpm %%v
  set PKG=pnpm
)

REM --- 6-9. Hardware profile via node one-liner (no extra deps) ---
echo  [6-9/12] Detecting hardware...
node -e "const o=require('os');console.log('  CPU: '+o.cpus()[0].model+' x'+o.cpus().length);console.log('  RAM: '+(o.totalmem()/1073741824).toFixed(1)+' GB');console.log('  Disk free: check during install');console.log('  GPU: discrete-GPU detection runs inside openagent setup')"
if errorlevel 1 echo  [!] hardware probe failed - continuing anyway.

REM --- 10. Local directories (per-user, no admin) ---
set OA_DATA=%LOCALAPPDATA%\OpenAgent\data
if not exist "%OA_DATA%\workspace" mkdir "%OA_DATA%\workspace" >nul 2>&1
if not exist "%OA_DATA%\logs" mkdir "%OA_DATA%\logs" >nul 2>&1
echo  [10/12] Local data dir: %OA_DATA%

REM --- 11. Install dependencies ---
echo  [11/12] Installing dependencies...
if "%PKG%"=="pnpm" (
  call pnpm install
) else (
  call npm install --no-audit --no-fund
)
if errorlevel 1 (
  echo(
  echo  OPENAGENT SETUP FAILED
  echo  Problem: dependency installation failed.
  echo  Recommended action: check network access, then re-run setup.cmd
  echo  Automatic repair: review the output above for the failing package.
  exit /b 1
)

REM --- 12. Build CLI (real entrypoint incl. bin/openagent.js) ---
echo  [12/12] Building OpenAgent CLI...
if "%PKG%"=="pnpm" (
  call pnpm --filter @openagent/cli build
) else (
  call npm --prefix packages/cli run build
)
if errorlevel 1 (
  echo(
  echo  OPENAGENT SETUP FAILED
  echo  Problem: CLI build failed.
  echo  Recommended action: run 'npx tsc --noEmit -p packages/cli/tsconfig.json' for details.
  exit /b 1
)

REM --- 13-14. Configure environment (.env, never overwrite) ---
if not exist ".env" (
  if exist ".env.example" (
    node scripts/setup.mjs --yes
  ) else (
    echo  [!] .env.example missing - skipping env generation.
  )
) else (
  echo  .env already exists - leaving it untouched.
)

REM --- 15-17. Browser/AI/migrations run through the real CLI setup ---
set SETUP_ARGS=setup --yes
echo %* | findstr /i "offline" >nul && set SETUP_ARGS=%SETUP_ARGS% --offline
echo %* | findstr /i "minimal" >nul && set SETUP_ARGS=%SETUP_ARGS% --minimal
echo %* | findstr /i "skip-model" >nul && set SETUP_ARGS=%SETUP_ARGS% --skip-model
node packages/cli/bin/openagent.js %SETUP_ARGS%
if errorlevel 1 (
  echo(
  echo  OPENAGENT SETUP FAILED
  echo  Problem: 'openagent setup' reported an error - see above.
  echo  Automatic repair: node packages/cli/bin/openagent.js repair
  exit /b 1
)

REM --- 18-19. Health check + smoke tests ---
node packages/cli/bin/openagent.js doctor
node packages/cli/bin/openagent.js --version >nul
if errorlevel 1 (
  echo  [X] CLI smoke test failed.
  exit /b 1
)
echo  CLI smoke test: OK (works from any directory after 'npm link' or installer)

REM --- 22-23. Dev CLI launcher (repo-local, no PATH edit required) ---
(
  echo @echo off
  echo node "%%~dp0packages\cli\bin\openagent.js" %%*
)> openagent-dev.cmd
echo  Created openagent-dev.cmd - repo-local launcher, no PATH change needed.

echo.
echo  OPENAGENT SETUP COMPLETE
echo.
echo  Next steps:
echo    openagent-dev.cmd doctor     # verify this checkout
echo    openagent-dev.cmd start      # start the local engine
echo.
echo  Optional global dev link (requires no admin, per-user npm prefix):
echo    npm link --prefix "%USERPROFILE%\.npm-global"  (run inside packages/cli)
echo.
