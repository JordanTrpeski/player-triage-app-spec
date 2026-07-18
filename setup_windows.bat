@echo off
REM Double-click setup for the rules-only application.
REM Delegates to setup_windows.ps1; pass -Dev for the test/type-check tooling.
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%setup_windows.ps1" %*
echo.
pause
endlocal
