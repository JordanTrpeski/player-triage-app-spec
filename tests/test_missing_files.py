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


def test_missing_policy_directory(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    # Remove the entire policy directory: manifest, vocab, everything.
    for child in list((root / "policy").iterdir()):
        if child.is_file():
            child.unlink()
        else:
            for sub in child.rglob("*"):
                if sub.is_file():
                    sub.unlink()
            for sub in sorted(child.rglob("*"), reverse=True):
                if sub.is_dir():
                    sub.rmdir()
            child.rmdir()
    (root / "policy").rmdir()

    with pytest.raises(MissingConfigurationError):
        load_app_config(root)
