"""Malformed JSON in a required configuration file must fail closed."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from player_triage.config import load_app_config
from player_triage.errors import InvalidConfigurationError


def test_invalid_json_in_controlled_vocabularies(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    (root / "policy" / "controlled_vocabularies.json").write_text(
        "{ not-json ]", encoding="utf-8"
    )

    with pytest.raises(InvalidConfigurationError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "controlled_vocabularies"
    assert "not valid JSON" in str(excinfo.value)


def test_invalid_json_in_policy_rules(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    (root / "policy" / "policy_rules.json").write_text("{\"rules\": [", encoding="utf-8")

    with pytest.raises(InvalidConfigurationError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "policy_rules"
