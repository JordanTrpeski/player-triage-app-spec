@echo off
REM ===========================================================================
REM  Reviewer-facing launcher.
REM
REM  A friendly wrapper around run_console.ps1 -- it adds no Streamlit
REM  configuration of its own. run_console.ps1 remains the single validated
REM  launch implementation, and keeps the hardened settings (local-only
REM  address, XSRF protection, suppressed error details, no usage statistics).
REM ===========================================================================
setlocal
cd /d "%~dp0"

REM Double-clicking passes no arguments, so the reviewer always gets 8501.
REM run_console.ps1 also accepts -Port; honour it here so the address shown
REM and the browser opened match the port actually served.
set "APP_PORT=8501"
if /i "%~1"=="-Port" if not "%~2"=="" set "APP_PORT=%~2"

echo ============================================================
echo    PLAYER CONTACT TRIAGE  --  OPERATOR CONSOLE
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo Setup has not been completed. Run SETUP_PLAYER_TRIAGE.bat first.
  echo.
  pause
  exit /b 1
)

if not exist "run_console.ps1" (
  echo Cannot start: run_console.ps1 is missing from this folder.
  echo Re-extract the package and try again.
  echo.
  pause
  exit /b 1
)

echo Mode    : rules_only  ^(no model is loaded or called^)
echo Address : http://localhost:%APP_PORT%
echo.
echo Your browser opens automatically once the application is ready.
echo If it does not, open this address yourself:
echo.
echo     http://localhost:%APP_PORT%
echo.
echo Keep this window open while you use the application.
echo Press Ctrl+C here, or close this window, to stop it.
echo.

REM Open the browser only once the server reports healthy, so the reviewer
REM never lands on a connection error. Detached, so the console stays in the
REM foreground and Ctrl+C continues to stop it. The repository pins
REM server.headless = true, which suppresses Streamlit's own browser launch;
REM that hardened setting is preserved rather than overridden here.
REM
REM Waits up to two minutes: the first launch after setup imports Streamlit
REM cold and is far slower than later ones. If it does still time out, the
REM address is printed above and the console is unaffected.
start "" /b powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$url='http://localhost:%APP_PORT%'; for($i=0; $i -lt 240; $i++){ try { $r = Invoke-WebRequest -Uri ($url + '/_stcore/health') -UseBasicParsing -TimeoutSec 2; if ($r.Content -match 'ok') { Start-Process $url; break } } catch { } Start-Sleep -Milliseconds 500 }"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_console.ps1" %*
set "RUN_EXIT=%ERRORLEVEL%"

REM Ctrl+C is a normal way to stop the console, not a launch failure.
if "%RUN_EXIT%"=="130" set "RUN_EXIT=0"
if "%RUN_EXIT%"=="-1073741510" set "RUN_EXIT=0"

if not "%RUN_EXIT%"=="0" (
  echo.
  echo ============================================================
  echo    The application stopped with exit code %RUN_EXIT%
  echo ============================================================
  echo.
  echo If the environment is missing or damaged, run
  echo SETUP_PLAYER_TRIAGE.bat again.
  echo.
  pause
)
exit /b %RUN_EXIT%
