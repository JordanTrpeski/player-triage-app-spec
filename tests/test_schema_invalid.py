"""Schema-invalid policy files must be rejected with a sanitized error."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from player_triage.config import load_app_config
from player_triage.errors import SchemaValidationError


def _write(root: Path, filename: str, document: object) -> None:
    (root / "policy" / filename).write_text(json.dumps(document), encoding="utf-8")


def test_schema_invalid_policy_rule_intent(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    original = json.loads((root / "policy" / "policy_rules.json").read_text(encoding="utf-8"))
    # Force an intent value that isn't in the controlled vocabulary.
    original["rules"][0]["effects"]["set"]["intent"] = "definitely_not_a_real_intent"
    _write(root, "policy_rules.json", original)

    with pytest.raises(SchemaValidationError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "policy_rules"
    assert "schema validation failed" in str(excinfo.value)


def test_schema_invalid_market_overlays_structure(
    mutated_app_root: Callable[[], Path],
) -> None:
    root = mutated_app_root()
    _write(root, "market_overlays.json", {"version": "3.0"})  # no overlays[]

    with pytest.raises(SchemaValidationError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "market_overlays"


def test_schema_invalid_configuration_manifest_hash(
    mutated_app_root: Callable[[], Path],
) -> None:
    root = mutated_app_root()
    document = json.loads((root / "policy" / "configuration_manifest.json").read_text(encoding="utf-8"))
    document["components"]["policy_rules"] = "not-a-sha256"
    _write(root, "configuration_manifest.json", document)

    with pytest.raises(SchemaValidationError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "configuration_manifest"
