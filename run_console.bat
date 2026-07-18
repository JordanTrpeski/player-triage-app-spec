@echo off
REM Double-click launcher for the local rules-only operator console.
REM Delegates to run_console.ps1; see that script for options.
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_console.ps1" %*
if errorlevel 1 (
  echo.
  echo The console exited with an error. Review the messages above.
  pause
)
endlocal
