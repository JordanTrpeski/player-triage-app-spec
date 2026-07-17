"""Phase 04 model-component activation, integrity and rollback governance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from player_triage.config import (
    EXPECTED_CONFIGURATION_VERSION,
    MODEL_CONFIGURATION_COMPONENT,
    load_app_config,
)
from player_triage.engine import TriageEngine
from player_triage.errors import HashIntegrityError
from player_triage.model.configuration import build_local_classifier, resolve_model_path
from player_triage.model.providers import DisabledSemanticClassifier, LocalModelSemanticClassifier
from player_triage.pipeline import ingest


def test_model_component_is_versioned_hash_verified_and_portable(app_root: Path) -> None:
    config = load_app_config(app_root)
    assert config.bundle_version == "policy-3.3.1" == EXPECTED_CONFIGURATION_VERSION
    assert config.has_component(MODEL_CONFIGURATION_COMPONENT)
    component = config.component(MODEL_CONFIGURATION_COMPONENT)
    assert component["version"] == "1.0.1"
    assert config.component_digest(MODEL_CONFIGURATION_COMPONENT)
    serialized = json.dumps(component)
    assert str(Path.home()) not in serialized
    assert ":\\" not in serialized


def test_default_model_reference_resolves_outside_repository(app_root: Path) -> None:
    config = load_app_config(app_root)
    path = resolve_model_path(config.component(MODEL_CONFIGURATION_COMPONENT))
    assert path.is_file()
    assert app_root not in path.parents
    assert path.suffix == ".gguf"


def test_environment_model_path_override_is_supported(
    app_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_app_config(app_root)
    override = tmp_path / "approved.gguf"
    monkeypatch.setenv("PLAYER_TRIAGE_MODEL_PATH", str(override))
    assert resolve_model_path(config.component(MODEL_CONFIGURATION_COMPONENT)) == override.resolve()


def test_model_component_hash_mismatch_fails_closed(
    mutated_app_root: Callable[[], Path],
) -> None:
    root = mutated_app_root()
    path = root / "policy" / "model_configuration.json"
    component = json.loads(path.read_text(encoding="utf-8"))
    component["timeout_seconds"] = 29
    path.write_text(json.dumps(component), encoding="utf-8")
    with pytest.raises(HashIntegrityError):
        load_app_config(root)


def test_policy_rules_hash_mismatch_fails_closed(
    mutated_app_root: Callable[[], Path],
) -> None:
    root = mutated_app_root()
    path = root / "policy" / "policy_rules.json"
    component = json.loads(path.read_text(encoding="utf-8"))
    component["version"] = "3.0.2"
    path.write_text(json.dumps(component), encoding="utf-8")
    with pytest.raises(HashIntegrityError):
        load_app_config(root)


def _roll_back_to_32(root: Path) -> None:
    archive = root / "policy" / "config_versions" / "policy-3.2.0"
    archived = archive / "configuration_manifest.json"
    (root / "policy" / "configuration_manifest.json").write_text(
        archived.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for name in (
        "policy_rules.json",
        "baseline_intent_rules.json",
        "redaction_policy.json",
        "derived_refinement_rules.json",
    ):
        (root / "policy" / name).write_bytes((archive / name).read_bytes())


def test_policy_32_rollback_loads_rules_only_and_preserves_results(
    app_root: Path, mutated_app_root: Callable[[], Path]
) -> None:
    root = mutated_app_root()
    _roll_back_to_32(root)
    rolled_config = load_app_config(root, strict_version=False)
    assert rolled_config.bundle_version == "policy-3.2.0"
    assert not rolled_config.has_component(MODEL_CONFIGURATION_COMPONENT)
    assert isinstance(build_local_classifier(rolled_config), DisabledSemanticClassifier)

    active_engine = TriageEngine.from_config(load_app_config(app_root))
    rolled_engine = TriageEngine.from_config(rolled_config)
    active = {m.msg_id: active_engine.classify(m).decision for m in ingest(active_engine.config)}
    rolled = {m.msg_id: rolled_engine.classify(m).decision for m in ingest(rolled_config)}
    for message_id in active:
        for field in ("category", "intent", "priority", "route", "assigned_team"):
            assert active[message_id][field] == rolled[message_id][field]


def test_policy_33_activation_builds_lazy_local_provider(app_root: Path) -> None:
    provider = build_local_classifier(load_app_config(app_root))
    assert isinstance(provider, LocalModelSemanticClassifier)
    assert provider.load_time_ms == 0


def test_archived_331_component_matches_active_bytes(app_root: Path) -> None:
    active = (app_root / "policy" / "model_configuration.json").read_bytes()
    archived = (
        app_root
        / "policy"
        / "config_versions"
        / "policy-3.3.1"
        / "model_configuration.json"
    ).read_bytes()
    assert active == archived


def test_failed_330_candidate_remains_immutable(app_root: Path) -> None:
    archive = app_root / "policy" / "config_versions" / "policy-3.3.0"
    manifest = json.loads((archive / "configuration_manifest.json").read_text(encoding="utf-8"))
    component = json.loads((archive / "model_configuration.json").read_text(encoding="utf-8"))
    assert manifest["version_id"] == "policy-3.3.0"
    assert manifest["components"]["policy_rules"] == (
        "1df7abc807638614825aa58470d2fb62a6e50ef5e629f8417ea334f8f364228c"
    )
    assert manifest["components"]["model_configuration"] == (
        "a5fc86cd6df75f6a58634ed3e9b016dbe986f01b26ef873be8445726d08fd21e"
    )
    assert component["version"] == "1.0.0"
