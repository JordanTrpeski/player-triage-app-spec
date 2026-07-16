"""A missing configuration file must fail closed with a sanitized error."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from player_triage.config import POLICY_COMPONENT_FILES, load_app_config
from player_triage.errors import MissingConfigurationError


@pytest.mark.parametrize("component_name", sorted(POLICY_COMPONENT_FILES))
def test_missing_component_file(
    mutated_app_root: Callable[[], Path], component_name: str
) -> None:
    root = mutated_app_root()
    (root / "policy" / POLICY_COMPONENT_FILES[component_name]).unlink()

    with pytest.raises(MissingConfigurationError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == component_name
    assert "required configuration file is not present" in str(excinfo.value)


def test_missing_policy_directory(tmp_path: Path) -> None:
    # Build an application root that has the schemas/ and input/ marker
    # directories but no policy/ directory at all, so loading must fail closed.
    #
    # This deliberately does NOT copy the authoritative policy/ or input/ files
    # into a temporary directory and then delete them: those files contain the
    # synthetic PAN/CVV/prompt-injection fixtures, and on Windows a real-time
    # antivirus scanner can hold a transient handle on the temp directory that
    # makes the follow-up rmdir raise PermissionError (WinError 5) — an
    # OS-level artifact unrelated to the behaviour under test. Never
    # materialising those fixtures avoids the lock while preserving the exact
    # purpose: a missing policy directory must fail closed with a sanitized
    # MissingConfigurationError.
    root = tmp_path / "app"
    root.mkdir()
    (root / "schemas").mkdir()
    (root / "input").mkdir()
    # policy/ is intentionally absent.

    with pytest.raises(MissingConfigurationError) as excinfo:
        load_app_config(root)

    # The failure is attributable to the absent policy directory, and the
    # sanitized message never contains dataset content.
    message = str(excinfo.value)
    assert "policy" in message.lower()
    assert excinfo.value.component in {"app_root", "policy"}
