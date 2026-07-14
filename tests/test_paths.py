"""Path resolution must be independent of the caller's cwd."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from player_triage.errors import MissingConfigurationError
from player_triage.paths import resolve_app_root


def test_resolve_app_root_ignores_cwd(app_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PLAYER_TRIAGE_APP_ROOT", raising=False)
    resolved = resolve_app_root()
    assert resolved == app_root


def test_resolve_app_root_env_override(tmp_path: Path, app_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYER_TRIAGE_APP_ROOT", str(app_root))
    monkeypatch.chdir(tmp_path)
    assert resolve_app_root() == app_root


def test_resolve_app_root_env_override_rejects_bad_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLAYER_TRIAGE_APP_ROOT", str(tmp_path))
    with pytest.raises(MissingConfigurationError):
        resolve_app_root()


def test_resolve_app_root_explicit_argument(app_root: Path) -> None:
    assert resolve_app_root(app_root) == app_root


def test_resolve_app_root_explicit_argument_rejects_bad_dir(tmp_path: Path) -> None:
    with pytest.raises(MissingConfigurationError):
        resolve_app_root(tmp_path)
