"""An unrecognized configuration_version must fail closed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from player_triage.config import EXPECTED_CONFIGURATION_VERSION, load_app_config
from player_triage.errors import UnknownVersionError


def test_unknown_configuration_version(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    manifest_path = root / "policy" / "configuration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version_id"] = "policy-9.9.9-experimental"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(UnknownVersionError) as excinfo:
        load_app_config(root)

    assert excinfo.value.component == "configuration_manifest"
    assert "policy-9.9.9-experimental" in str(excinfo.value)
    assert EXPECTED_CONFIGURATION_VERSION in str(excinfo.value)


def test_relaxed_mode_permits_alternate_version(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    manifest_path = root / "policy" / "configuration_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version_id"] = "policy-3.0.0-preview"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    config = load_app_config(root, strict_version=False)
    assert config.configuration_version == "policy-3.0.0-preview"
