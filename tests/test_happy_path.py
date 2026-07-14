"""Every authoritative policy file loads and the AppConfig is internally consistent."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from player_triage.config import (
    EXPECTED_CONFIGURATION_VERSION,
    POLICY_COMPONENT_FILES,
    AppConfig,
    load_app_config,
)


def test_load_all_components(app_root: Path) -> None:
    config = load_app_config(app_root)
    assert set(config.components) == set(POLICY_COMPONENT_FILES)
    assert config.configuration_version == EXPECTED_CONFIGURATION_VERSION
    assert config.vocab.version == "3.0"
    for name in POLICY_COMPONENT_FILES:
        raw = config.component(name)
        assert isinstance(raw, dict)


def test_app_config_is_immutable(app_root: Path) -> None:
    config = load_app_config(app_root)
    assert dataclasses.is_dataclass(config) and getattr(config, "__dataclass_params__").frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.app_root = Path("/tmp/other")  # type: ignore[misc]


def test_component_versions_match_manifest_children(app_root: Path) -> None:
    config = load_app_config(app_root)
    for name, version in config.component_versions().items():
        assert version, f"component {name!r} has an empty version"


def test_schema_registry_registers_all_shipped_schemas(app_root: Path) -> None:
    config = load_app_config(app_root)
    directory = app_root / "schemas"
    expected = {path.name for path in directory.glob("*.json")}
    assert set(config.schema_registry.ids) == expected
    assert len(config.schema_registry.schemas) == len(expected)


def test_expected_configuration_version_symbol_matches_manifest(app_root: Path) -> None:
    config = load_app_config(app_root)
    assert config.manifest.version_id == EXPECTED_CONFIGURATION_VERSION
