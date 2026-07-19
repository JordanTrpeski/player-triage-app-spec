@echo off
REM ===========================================================================
REM  Reviewer-facing one-time setup.
REM
REM  A friendly wrapper around setup_windows.ps1 -- it adds no installation
REM  logic of its own. setup_windows.ps1 remains the single validated setup
REM  implementation and may still be run directly.
REM ===========================================================================
setlocal
cd /d "%~dp0"

echo ============================================================
echo    PLAYER CONTACT TRIAGE  --  ONE-TIME SETUP
echo ============================================================
echo.
echo This prepares a local Python environment for the application.
echo You only need to run it once.
echo.
echo Requirements:
echo   - Windows 10 or later
echo   - Python 3.12
echo   - internet access during this step only
echo.
echo The delivered runtime is rules-only. No local model runtime
echo and no model file are installed or downloaded.
echo.
echo This can take a few minutes. Please wait.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1" %*
set "SETUP_EXIT=%ERRORLEVEL%"

echo.
if not "%SETUP_EXIT%"=="0" (
  echo ============================================================
  echo    SETUP FAILED  ^(exit code %SETUP_EXIT%^)
  echo ============================================================
  echo.
  echo The messages above give the reason. The most common cause is
  echo a missing Python 3.12. Check it with:
  echo.
  echo     py -3.12 --version
  echo.
  echo Fix the cause and run this file again.
  echo.
  pause
  exit /b %SETUP_EXIT%
)

echo ============================================================
echo    Setup completed successfully
echo ============================================================
echo.
echo Next step: double-click START_PLAYER_TRIAGE.bat
echo.
pause
exit /b 0
