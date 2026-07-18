<#
.SYNOPSIS
    Clean-machine setup for the rules-only Player Contact Triage application.

.DESCRIPTION
    Creates a fresh virtual environment, installs the pinned rules-only
    dependency set, installs this package without pulling additional
    dependencies, and runs a health check.

    The rejected local-model runtime (llama-cpp-python) and any GGUF model
    artifact are deliberately NOT installed. The delivered application runs in
    rules_only mode and performs zero model calls.

    Compatible with Windows PowerShell 5.1.

.PARAMETER Dev
    Also install pytest and mypy (requirements-dev.lock) so the release suite
    and type checks can be run.

.PARAMETER Force
    Recreate the virtual environment even if one already exists.

.EXAMPLE
    .\setup_windows.ps1

.EXAMPLE
    .\setup_windows.ps1 -Dev
#>
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvDir = Join-Path $RepoRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

if ($Dev) {
    $LockFile = Join-Path $RepoRoot 'requirements-dev.lock'
    $LockLabel = 'requirements-dev.lock (rules-only runtime + pytest + mypy)'
} else {
    $LockFile = Join-Path $RepoRoot 'requirements-rules-only.lock'
    $LockLabel = 'requirements-rules-only.lock (delivered rules-only runtime)'
}

function Write-Step { param([string]$Text) Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "OK  $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "!!  $Text" -ForegroundColor Yellow }

Write-Host 'Player Contact Triage - rules-only setup' -ForegroundColor White
Write-Host "Repository: $RepoRoot"
Write-Host "Lock file : $LockLabel"

# --- 1. Python version ------------------------------------------------------
Write-Step 'Checking Python'
$pythonExe = $null
foreach ($candidate in @('py -3.12', 'python')) {
    $parts = $candidate -split ' ', 2
    $exe = $parts[0]
    $argsList = if ($parts.Count -gt 1) { $parts[1] } else { '' }
    $found = Get-Command $exe -ErrorAction SilentlyContinue
    if ($null -eq $found) { continue }
    if ($argsList) {
        $version = & $exe $argsList --version 2>$null
    } else {
        $version = & $exe --version 2>$null
    }
    if ($LASTEXITCODE -eq 0 -and $version -match '3\.12\.') {
        $pythonExe = $candidate
        Write-Ok "$version"
        break
    }
}
if ($null -eq $pythonExe) {
    throw 'Python 3.12 is required and was not found. Install Python 3.12 and re-run this script.'
}

# --- 2. Virtual environment -------------------------------------------------
Write-Step 'Preparing virtual environment'
if ((Test-Path $VenvDir) -and $Force) {
    Write-Warn 'Removing existing .venv (-Force)'
    Remove-Item -Recurse -Force $VenvDir
}
if (-not (Test-Path $VenvPython)) {
    $parts = $pythonExe -split ' ', 2
    if ($parts.Count -gt 1) {
        & $parts[0] $parts[1] -m venv $VenvDir
    } else {
        & $parts[0] -m venv $VenvDir
    }
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the virtual environment.' }
    Write-Ok "created $VenvDir"
} else {
    Write-Ok 'reusing existing .venv (pass -Force to recreate)'
}

# --- 3. Dependencies --------------------------------------------------------
Write-Step 'Installing pinned dependencies'
if (-not (Test-Path $LockFile)) { throw "Lock file not found: $LockFile" }

& $VenvPython -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Failed to upgrade pip.' }

& $VenvPython -m pip install --quiet -r $LockFile
if ($LASTEXITCODE -ne 0) { throw 'Failed to install pinned dependencies.' }
Write-Ok 'pinned dependencies installed'

# --no-deps: the lock file is authoritative. This prevents pip from resolving
# anything beyond the pinned set.
& $VenvPython -m pip install --quiet --no-deps --editable $RepoRoot
if ($LASTEXITCODE -ne 0) { throw 'Failed to install the player_triage package.' }
Write-Ok 'player_triage installed (--no-deps)'

# --- 4. Health check --------------------------------------------------------
Write-Step 'Health check'

# Checked in Python rather than via `pip show`: on Windows PowerShell 5.1 a
# native command writing to stderr (as pip does for a missing package) is
# surfaced as a NativeCommandError and would abort the script.
$modelPresent = & $VenvPython -c "import importlib.util; print('yes' if importlib.util.find_spec('llama_cpp') else 'no')"
if ($LASTEXITCODE -ne 0) { throw 'Local-model presence check failed.' }
if ($modelPresent -eq 'yes') {
    Write-Warn 'llama-cpp-python is present in this environment.'
    Write-Warn 'The delivered application is rules-only and does not require it.'
} else {
    Write-Ok 'local-model runtime absent (expected for the delivered runtime)'
}

& $VenvPython -c "import streamlit, openpyxl, jsonschema, typer; print('OK  runtime imports: streamlit ' + streamlit.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Runtime import check failed.' }

& $VenvPython -c "import sys, player_triage.cli, player_triage.ui.app; leaked=[m for m in sys.modules if 'llama' in m.lower()]; print('OK  no local-model import: ' + (', '.join(leaked) if leaked else 'confirmed')); sys.exit(1 if leaked else 0)"
if ($LASTEXITCODE -ne 0) { throw 'A local-model module was imported during startup.' }

& $VenvPython -m player_triage.cli validate-policy
if ($LASTEXITCODE -ne 0) { throw 'Policy validation failed.' }

& $VenvPython (Join-Path $RepoRoot 'tools\validate_policy_package.py')
if ($LASTEXITCODE -ne 0) { throw 'Policy package validation failed.' }

& $VenvPython (Join-Path $RepoRoot 'tools\validate_application_spec.py')
if ($LASTEXITCODE -ne 0) { throw 'Application spec validation failed.' }

# --- 5. Done ----------------------------------------------------------------
Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host 'Start the console with:  .\run_console.ps1'
Write-Host 'Run the supplied-40 set:  .\.venv\Scripts\python.exe -m player_triage.cli run --mode rules_only'
if ($Dev) {
    Write-Host 'Run the release suite:    .\.venv\Scripts\python.exe -m pytest -q'
}
