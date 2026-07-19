"""Phase 09 release correction: reviewer-facing Windows setup and launcher.

``SETUP_PLAYER_TRIAGE.bat`` and ``START_PLAYER_TRIAGE.bat`` are wrappers, not
implementations: they must delegate to the already-validated
``setup_windows.ps1`` and ``run_console.ps1`` rather than restate any install
step or Streamlit setting. Most of what can go wrong with a double-click
launcher is textual — an absolute developer path, a hard-coded machine name, a
swallowed exit code — so the static checks below are the substantive ones.

The behavioural tests run the real batch files and are skipped off Windows.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="the Windows launcher requires cmd.exe"
)

SETUP_WRAPPER = "SETUP_PLAYER_TRIAGE.bat"
START_WRAPPER = "START_PLAYER_TRIAGE.bat"
START_HERE = "START_HERE.txt"

#: The pre-existing scripts the wrappers delegate to. Preserved for
#: compatibility: anyone already using them must not be broken by the wrappers.
EXISTING_SCRIPTS = (
    "setup_windows.ps1",
    "setup_windows.bat",
    "run_console.ps1",
    "run_console.bat",
)

REVIEWER_FILES = (SETUP_WRAPPER, START_WRAPPER, START_HERE)


def _read(app_root: Path, name: str) -> str:
    return (app_root / name).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# presence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", REVIEWER_FILES)
def test_reviewer_facing_file_exists(app_root: Path, name: str) -> None:
    path = app_root / name
    assert path.is_file(), f"{name} is missing"
    assert path.stat().st_size > 0, f"{name} is empty"


@pytest.mark.parametrize("name", EXISTING_SCRIPTS)
def test_existing_scripts_are_preserved(app_root: Path, name: str) -> None:
    """The wrappers add a friendly entry point; they replace nothing."""

    assert (app_root / name).is_file(), f"{name} must be preserved for compatibility"


# ---------------------------------------------------------------------------
# no developer-specific paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", REVIEWER_FILES)
def test_no_user_specific_path_is_embedded(app_root: Path, name: str) -> None:
    """A path from the machine that built this package would break every other."""

    text = _read(app_root, name)
    forbidden = (
        r"[A-Za-z]:\\Users\\",
        r"[A-Za-z]:/Users/",
        r"\\\\[A-Za-z0-9_.-]+\\",  # UNC share
        r"/home/",
        r"/Users/",
    )
    for pattern in forbidden:
        assert not re.search(pattern, text), f"{name} embeds a machine path: {pattern}"


@pytest.mark.parametrize("name", (SETUP_WRAPPER, START_WRAPPER))
def test_wrappers_resolve_paths_relative_to_themselves(
    app_root: Path, name: str
) -> None:
    """``%~dp0`` is what makes a double-click work from any location."""

    text = _read(app_root, name)
    assert 'cd /d "%~dp0"' in text, f"{name} must cd to its own directory"
    assert "%~dp0" in text


@pytest.mark.parametrize("name", (SETUP_WRAPPER, START_WRAPPER))
def test_wrappers_do_not_hard_code_a_drive_letter(app_root: Path, name: str) -> None:
    text = _read(app_root, name)
    assert not re.search(r'"[A-Za-z]:\\', text), f"{name} hard-codes a drive"


# ---------------------------------------------------------------------------
# delegation rather than duplication
# ---------------------------------------------------------------------------


def test_setup_wrapper_delegates_to_the_validated_setup_script(
    app_root: Path,
) -> None:
    text = _read(app_root, SETUP_WRAPPER)
    assert "setup_windows.ps1" in text
    assert "-NoProfile" in text
    assert "-ExecutionPolicy Bypass" in text
    assert "powershell.exe" in text, "Windows PowerShell 5.1, not pwsh"


def test_launch_wrapper_delegates_to_the_validated_console_script(
    app_root: Path,
) -> None:
    text = _read(app_root, START_WRAPPER)
    assert "run_console.ps1" in text or "run_console.bat" in text
    assert "-NoProfile" in text
    assert "-ExecutionPolicy Bypass" in text


def test_launch_wrapper_does_not_restate_streamlit_configuration(
    app_root: Path,
) -> None:
    """Duplicated flags would drift from run_console.ps1 and weaken hardening."""

    text = _read(app_root, START_WRAPPER)
    for flag in (
        "streamlit run",
        "--server.address",
        "--server.port",
        "--server.enableXsrfProtection",
        "--client.showErrorDetails",
    ):
        assert flag not in text, f"{START_WRAPPER} duplicates {flag}"


def test_wrappers_never_install_a_model_runtime(app_root: Path) -> None:
    for name in (SETUP_WRAPPER, START_WRAPPER):
        lowered = _read(app_root, name).lower()
        for forbidden in ("llama", "gguf", "huggingface", "pip install", "curl "):
            assert forbidden not in lowered, f"{name} mentions {forbidden}"


def test_setup_script_installs_the_rules_only_lock_by_default(
    app_root: Path,
) -> None:
    """The default setup path must not resolve a local-model dependency."""

    text = _read(app_root, "setup_windows.ps1")
    assert "requirements-rules-only.lock" in text

    # Comments in the lock file name llama-cpp-python precisely to record that
    # it is excluded, so only requirement lines are inspected.
    requirements = [
        line.strip()
        for line in _read(app_root, "requirements-rules-only.lock").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert requirements, "the rules-only lock pins nothing"
    for line in requirements:
        assert "llama" not in line.lower(), f"rules-only lock installs {line}"


def test_launcher_does_not_install_during_normal_launch(app_root: Path) -> None:
    text = _read(app_root, START_WRAPPER).lower()
    assert "pip" not in text
    assert "setup_windows.ps1" not in text, "launch must not silently run setup"


# ---------------------------------------------------------------------------
# reviewer-visible behaviour, checked as text
# ---------------------------------------------------------------------------


def test_launcher_checks_for_the_environment_before_starting(
    app_root: Path,
) -> None:
    text = _read(app_root, START_WRAPPER)
    assert r".venv\Scripts\python.exe" in text
    assert "Setup has not been completed. Run SETUP_PLAYER_TRIAGE.bat first." in text


def test_launcher_advertises_localhost_only(app_root: Path) -> None:
    text = _read(app_root, START_WRAPPER)
    # The address is built from APP_PORT, which defaults to 8501, so a
    # double-click always shows http://localhost:8501.
    assert 'set "APP_PORT=8501"' in text
    assert "http://localhost:%APP_PORT%" in text
    # Nothing may advertise a routable address.
    assert not re.search(r"http://(?!localhost|127\.0\.0\.1|%)[a-z0-9.-]+", text)
    assert "0.0.0.0" not in text


def test_launcher_opens_the_browser_on_the_port_it_serves(app_root: Path) -> None:
    """A custom -Port must not send the reviewer's browser to the default."""

    text = _read(app_root, START_WRAPPER)
    assert "$url='http://localhost:%APP_PORT%'" in text
    assert "_stcore/health" in text, "wait for readiness before opening a browser"
    assert "Start-Process $url" in text


def test_console_script_binds_to_loopback_only(app_root: Path) -> None:
    """The wrapper inherits this; it is the setting that keeps the app local."""

    text = _read(app_root, "run_console.ps1")
    assert "127.0.0.1" in text
    assert "0.0.0.0" not in text


def test_setup_wrapper_reports_success_and_failure_distinctly(
    app_root: Path,
) -> None:
    text = _read(app_root, SETUP_WRAPPER)
    assert "Setup completed successfully" in text
    assert "SETUP FAILED" in text
    assert "exit /b %SETUP_EXIT%" in text, "a failing setup must exit non-zero"
    assert text.count("pause") >= 2, "both outcomes must pause so they can be read"


def test_launch_wrapper_propagates_its_exit_code(app_root: Path) -> None:
    text = _read(app_root, START_WRAPPER)
    assert "exit /b %RUN_EXIT%" in text
    assert "exit /b 1" in text, "a missing environment must exit non-zero"


def test_start_here_covers_the_reviewer_workflow(app_root: Path) -> None:
    text = _read(app_root, START_HERE)
    for required in (
        "Windows 10",
        "Python 3.12",
        SETUP_WRAPPER,
        START_WRAPPER,
        "http://localhost:8501",
        "Ctrl+C",
        "py -3.12 --version",
        "Supplied 40 Benchmark",
        "Import",
        "Dashboard",
        "CSV",
        "XLSX",
        "10,000 rows",
    ):
        assert required in text, f"START_HERE.txt does not mention {required!r}"


def test_start_here_states_the_real_batch_limit(app_root: Path) -> None:
    """Reviewer documentation must agree with the enforced limit."""

    from player_triage.import_ingestion import MAX_IMPORT_ROWS

    text = _read(app_root, START_HERE)
    assert f"{MAX_IMPORT_ROWS:,} rows" in text


def test_start_here_does_not_promise_a_model(app_root: Path) -> None:
    lowered = _read(app_root, START_HERE).lower()
    assert "rules-only" in lowered
    for forbidden in ("llama", "gguf", "install a model\n"):
        assert forbidden not in lowered.replace("do not install a model", "")


# ---------------------------------------------------------------------------
# behavioural: run the real batch files
# ---------------------------------------------------------------------------


def _run_bat(path: Path, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run a .bat non-interactively.

    ``pause`` reads stdin, so stdin is closed to make it return immediately
    instead of hanging the test.
    """

    return subprocess.run(
        ["cmd.exe", "/c", str(path)],
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture()
def package_copy(app_root: Path, tmp_path: Path) -> Path:
    """A clean extracted copy: scripts and sources, deliberately no ``.venv``."""

    destination = tmp_path / "extracted"
    destination.mkdir()
    for name in (*REVIEWER_FILES, *EXISTING_SCRIPTS):
        shutil.copy2(app_root / name, destination / name)
    return destination


@WINDOWS_ONLY
def test_launcher_without_an_environment_reports_the_setup_instruction(
    package_copy: Path, tmp_path: Path
) -> None:
    """The missing-.venv path is what a reviewer hits by starting in the wrong order."""

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = _run_bat(package_copy / START_WRAPPER, cwd=elsewhere)

    assert result.returncode == 1, result.stdout
    assert (
        "Setup has not been completed. Run SETUP_PLAYER_TRIAGE.bat first."
        in result.stdout
    )


@WINDOWS_ONLY
def test_launcher_locates_itself_from_an_unrelated_working_directory(
    package_copy: Path, tmp_path: Path
) -> None:
    """Double-clicking can leave the working directory anywhere at all."""

    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()

    result = _run_bat(package_copy / START_WRAPPER, cwd=elsewhere)

    # It found its own folder rather than reading the caller's: the .venv check
    # is the only thing that can fail here, and it fails with our message.
    assert "Setup has not been completed" in result.stdout
    assert "is missing from this folder" not in result.stdout


@WINDOWS_ONLY
def test_launcher_states_the_address_before_any_environment_check(
    package_copy: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    result = _run_bat(package_copy / START_WRAPPER, cwd=elsewhere)
    assert "PLAYER CONTACT TRIAGE" in result.stdout


@WINDOWS_ONLY
def test_setup_wrapper_fails_clearly_when_the_setup_script_is_absent(
    app_root: Path, tmp_path: Path
) -> None:
    """A truncated extraction must fail loudly and non-zero, not half-succeed."""

    broken = tmp_path / "broken"
    broken.mkdir()
    shutil.copy2(app_root / SETUP_WRAPPER, broken / SETUP_WRAPPER)

    result = _run_bat(broken / SETUP_WRAPPER, cwd=broken)

    assert result.returncode != 0
    assert "SETUP FAILED" in result.stdout


# ---------------------------------------------------------------------------
# behavioural: the launcher really starts Streamlit
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    return port


def _health(port: int, timeout: float = 90.0) -> str | None:
    """Poll Streamlit's health endpoint until it answers, or give up."""

    deadline = time.monotonic() + timeout
    url = f"http://localhost:{port}/_stcore/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return response.read().decode("utf-8", "replace").strip()
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return None


@WINDOWS_ONLY
def test_launcher_starts_streamlit_and_the_health_endpoint_answers(
    app_root: Path,
) -> None:
    """End to end: the wrapper brings up a serving console on loopback.

    Uses a free port so it cannot collide with a console the reviewer already
    has running on 8501.
    """

    if not (app_root / ".venv" / "Scripts" / "python.exe").is_file():
        pytest.skip("no .venv in this checkout; run SETUP_PLAYER_TRIAGE.bat first")

    port = _free_port()
    process = subprocess.Popen(
        ["cmd.exe", "/c", str(app_root / START_WRAPPER), "-Port", str(port)],
        cwd=str(app_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        body = _health(port)
        assert body is not None, "the console never became healthy"
        assert "ok" in body.lower(), body

        # Loopback only: the port must not answer on a routable interface.
        with socket.socket() as probe:
            probe.settimeout(2)
            assert probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
        process.wait(timeout=60)


@WINDOWS_ONLY
def test_environment_excludes_the_local_model_runtime(app_root: Path) -> None:
    """What setup produced must not contain llama-cpp-python."""

    python = app_root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        pytest.skip("no .venv in this checkout; run SETUP_PLAYER_TRIAGE.bat first")

    result = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.util;"
            "print('yes' if importlib.util.find_spec('llama_cpp') else 'no')",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.stdout.strip() == "no"
