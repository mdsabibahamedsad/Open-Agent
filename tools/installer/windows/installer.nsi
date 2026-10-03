; OpenAgent-Setup.exe — NSIS wrapper (per-user, no admin required).
; Build (CI, Windows): makensis tools/installer/windows/installer.nsi
;   with payload staged at dist/windows-nsis/OpenAgent first
;   (see: npm run package:windows).
; Code signing: sign the output with signtool before publishing.

!include "MUI2.nsh"

Name "OpenAgent"
OutFile "..\..\..\dist\OpenAgent-Setup.exe"
InstallDir "$LOCALAPPDATA\OpenAgent"
RequestExecutionLevel user
ShowInstDetails show
SetCompressor /SOLID lzma

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

VIProductVersion "1.0.0.0"
VIAddVersionKey "ProductName" "OpenAgent"
VIAddVersionKey "FileDescription" "OpenAgent local AI automation platform"
VIAddVersionKey "LegalCopyright " "MIT"

Section "OpenAgent" SecCore
  SectionIn RO
  SetOutPath "$INSTDIR"
  ; Payload staged by scripts/package-windows.mjs (app files + installer PS1s).
  File /r "..\..\..\dist\windows-nsis\OpenAgent\*.*"
  ; Single source of truth: the PowerShell installer performs configuration.
  ExecWait 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\tools\installer\windows\Install-OpenAgent.ps1" -Silent -Source "$INSTDIR\payload\openagent-win-x64.zip"' $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "OpenAgent installation did not complete (code $0). The installer left no half-configured services behind — re-run to retry."
    Abort
  ${EndIf}
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  ExecWait 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\tools\installer\windows\Uninstall-OpenAgent.ps1"'
  Delete "$INSTDIR\Uninstall.exe"
  ; User data under $INSTDIR\data is intentionally preserved.
SectionEnd
