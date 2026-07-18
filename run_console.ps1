<#
.SYNOPSIS
    Launch the local rules-only operator console (Streamlit).

.DESCRIPTION
    Starts the Streamlit control console bound to 127.0.0.1 using the
    repository's .streamlit/config.toml. The console runs in rules_only mode
    and makes zero model calls.

    Run setup_windows.ps1 first if the virtual environment does not yet exist.

    Compatible with Windows PowerShell 5.1.

.PARAMETER Port
    Port to serve on. Defaults to 8501.

.PARAMETER NoBrowser
    Do not open a browser window automatically.

.EXAMPLE
    .\run_console.ps1

.EXAMPLE
    .\run_console.ps1 -Port 8600 -NoBrowser
#>
[CmdletBinding()]
param(
    [int]$Port = 8501,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$AppFile = Join-Path $RepoRoot 'src\player_triage\ui\app.py'

if (-not (Test-Path $VenvPython)) {
    Write-Host 'Virtual environment not found.' -ForegroundColor Yellow
    Write-Host 'Run .\setup_windows.ps1 first.' -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $AppFile)) {
    throw "Console entry point not found: $AppFile"
}

# Pin the application root so console operations never depend on the caller's
# working directory.
$env:PLAYER_TRIAGE_APP_ROOT = $RepoRoot

# Streamlit only reads .streamlit/config.toml from the current working
# directory (or the user profile). Launching from elsewhere silently discards
# the repository's hardened settings -- local-only address, headless mode, XSRF
# protection, suppressed error details and disabled usage statistics. Switching
# to the repository root makes that configuration apply regardless of where the
# launcher was invoked from.
Set-Location $RepoRoot

Write-Host 'Player Contact Triage - operator console' -ForegroundColor White
Write-Host "Mode      : rules_only (model rejected and unavailable)"
Write-Host "App root  : $RepoRoot"
Write-Host "URL       : http://127.0.0.1:$Port"
Write-Host 'Press Ctrl+C to stop.'
Write-Host ''

# The privacy- and safety-relevant settings are passed explicitly as well as
# living in .streamlit/config.toml, so they hold even if that file is missing.
$streamlitArgs = @(
    '-m', 'streamlit', 'run', $AppFile,
    '--server.address', '127.0.0.1',
    '--server.port', "$Port",
    '--browser.gatherUsageStats', 'false',
    '--server.enableXsrfProtection', 'true',
    '--client.showErrorDetails', 'false'
)
if ($NoBrowser) {
    $streamlitArgs += @('--server.headless', 'true')
}

& $VenvPython $streamlitArgs
exit $LASTEXITCODE
