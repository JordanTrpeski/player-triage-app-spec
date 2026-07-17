"""Phase 03C governance tests for the derived_refinement_rules policy component.

Covers loader discovery, missing/malformed/schema/hash-integrity failures, UI
editability discovery, configuration-version activation and rollback (rollback
restores pre-derived behavior), and audit-event provenance. Mutations happen in a
copied temporary bundle so the authoritative policy/ is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
from jsonschema import Draft202012Validator

from player_triage.config import (
    DERIVED_REFINEMENT_COMPONENT,
    EXPECTED_CONFIGURATION_VERSION,
    load_app_config,
)
from player_triage.engine import TriageEngine
from player_triage.errors import (
    HashIntegrityError,
    InvalidConfigurationError,
    MissingConfigurationError,
    SchemaValidationError,
)
from player_triage.pipeline import ingest as run_ingest

_DERIVED_FILE = "derived_refinement_rules.json"


# -- loader discovery -------------------------------------------------------
def test_component_is_loaded_and_versioned(app_root: Path) -> None:
    config = load_app_config(app_root)
    assert config.has_component(DERIVED_REFINEMENT_COMPONENT)
    component = config.component(DERIVED_REFINEMENT_COMPONENT)
    # The derived component file is unchanged since 03C (internal version 3.1.0);
    # the active policy bundle may advance while retaining this governed component.
    assert component["version"] == "3.1.0"
    assert len(component["rules"]) == 8
    assert config.bundle_version == EXPECTED_CONFIGURATION_VERSION
    assert config.component_digest(DERIVED_REFINEMENT_COMPONENT)


def test_no_source_level_fallback_copy(app_root: Path) -> None:
    # The policy content must live only under policy/, not under src/.
    assert not (app_root / "src" / "player_triage" / "phase03_derived_rules.json").exists()


# -- missing / malformed / schema / hash -----------------------------------
def test_missing_declared_component_fails(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    (root / "policy" / _DERIVED_FILE).unlink()
    with pytest.raises(MissingConfigurationError):
        load_app_config(root)


def test_malformed_component_fails(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    (root / "policy" / _DERIVED_FILE).write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(InvalidConfigurationError):
        load_app_config(root)


def test_schema_invalid_component_fails(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    bad = {"version": "3.1.0", "rules": [{"id": "not-a-valid-id", "when": {}}]}
    (root / "policy" / _DERIVED_FILE).write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SchemaValidationError):
        load_app_config(root)


def test_hash_mismatch_fails(mutated_app_root: Callable[[], Path]) -> None:
    root = mutated_app_root()
    path = root / "policy" / _DERIVED_FILE
    component = json.loads(path.read_text(encoding="utf-8"))
    # Schema-valid but different bytes -> digest no longer matches the manifest.
    component["description"] = component["description"] + " (tampered)"
    path.write_text(json.dumps(component), encoding="utf-8")
    with pytest.raises(HashIntegrityError):
        load_app_config(root)


# -- UI editability discovery ----------------------------------------------
def test_ui_editability_discovers_component(app_root: Path) -> None:
    ui = json.loads((app_root / "policy" / "ui_editability.json").read_text(encoding="utf-8"))
    assert DERIVED_REFINEMENT_COMPONENT in ui["components"]
    entry = ui["components"][DERIVED_REFINEMENT_COMPONENT]
    assert entry.get("discoverable") is True
    rule_editability = entry["rule_editability"]
    component = json.loads(
        (app_root / "policy" / _DERIVED_FILE).read_text(encoding="utf-8")
    )
    rule_ids = {r["id"] for r in component["rules"]}
    # Every rule is classified, and only locked/guarded/editable are used.
    assert set(rule_editability) == rule_ids
    assert set(rule_editability.values()) <= {"locked", "guarded", "editable"}
    # Policy Studio lifecycle is available.
    assert "rollback_available" in ui["workflow"]
    assert "activate_or_reject" in ui["workflow"]


def test_traceability_present_for_every_rule(app_root: Path) -> None:
    trace = json.loads(
        (app_root / "policy" / "research_traceability.json").read_text(encoding="utf-8")
    )
    entries = {e["rule_id"]: e for e in trace["derived_rule_traceability"]}
    component = json.loads((app_root / "policy" / _DERIVED_FILE).read_text(encoding="utf-8"))
    for rule in component["rules"]:
        entry = entries[rule["id"]]
        assert entry["control_classification"] in {
            "direct_regulatory_requirement",
            "official_guidance",
            "conservative_prototype_control",
            "operational_routing_decision",
        }
        assert entry["owner"] and entry["rationale"] and entry["review_requirement"]
        assert entry["affected_output_fields"]
        # Operational routing choices must not be labelled a direct legal requirement.
        if entry["control_classification"] == "operational_routing_decision":
            assert "regulatory" not in entry["control_classification"]


# -- activation vs rollback -------------------------------------------------
def _rollback_root(mutated_app_root: Callable[[], Path]) -> Path:
    root = mutated_app_root()
    # Restore the archived policy-3.0.0 manifest (no derived component) and remove
    # the derived component file -> a genuine rollback to pre-derived behavior.
    archived = root / "policy" / "config_versions" / "policy-3.0.0" / "configuration_manifest.json"
    (root / "policy" / "configuration_manifest.json").write_text(
        archived.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "policy" / _DERIVED_FILE).unlink()
    return root


def test_activation_has_component(app_root: Path) -> None:
    config = load_app_config(app_root)
    assert config.bundle_version == EXPECTED_CONFIGURATION_VERSION
    assert config.has_component(DERIVED_REFINEMENT_COMPONENT)


def test_rollback_removes_component(mutated_app_root: Callable[[], Path]) -> None:
    root = _rollback_root(mutated_app_root)
    config = load_app_config(root, strict_version=False)
    assert config.bundle_version == "policy-3.0.0"
    assert not config.has_component(DERIVED_REFINEMENT_COMPONENT)


def test_rollback_restores_pre_derived_behavior(
    app_root: Path, mutated_app_root: Callable[[], Path]
) -> None:
    # Active bundle: a duplicate-card-charge is elevated to high/specialist.
    active = TriageEngine.from_config(load_app_config(app_root))
    active_by_id = {m.msg_id: active.classify(m).decision for m in run_ingest(active.config)}
    assert active_by_id["M35"]["priority"] == "high"
    assert active_by_id["M35"]["route"] == "specialist"

    # Rolled-back bundle: the derived component is gone -> pre-derived medium/human.
    root = _rollback_root(mutated_app_root)
    rolled = TriageEngine.from_config(load_app_config(root, strict_version=False))
    rolled_by_id = {m.msg_id: rolled.classify(m).decision for m in run_ingest(rolled.config)}
    assert rolled_by_id["M35"]["priority"] == "medium"
    assert rolled_by_id["M35"]["route"] == "human"
    # Safety outcomes are unaffected by the rollback.
    assert rolled_by_id["M07"]["priority"] == "critical"
    assert rolled_by_id["M11"]["model_called"] is False


# -- audit provenance -------------------------------------------------------
def test_decision_audit_event_records_provenance(app_root: Path) -> None:
    config = load_app_config(app_root)
    engine = TriageEngine.from_config(config)
    schema = config.schema_registry
    audit_id = schema.ids["audit_event_schema.json"]
    validator: Draft202012Validator = schema.validator(audit_id)

    messages = {m.msg_id: m for m in run_ingest(config)}
    # M35 triggers a derived rule; the audit event must be schema-valid and carry
    # the bundle version, component version/digest and triggered derived rule ids.
    result = engine.classify(messages["M35"])
    event = engine.build_decision_audit_event(result)
    assert list(validator.iter_errors(event)) == []
    prov = event["payload"]["component_provenance"]
    assert prov["policy_bundle_version"] == EXPECTED_CONFIGURATION_VERSION
    assert prov["derived_refinement_version"] == "3.1.0"
    assert prov["derived_refinement_digest"] == config.component_digest(DERIVED_REFINEMENT_COMPONENT)
    assert "DERIVED_DUPLICATE_CARD_CHARGE" in prov["derived_rules_triggered"]
    assert event["configuration_version"] == EXPECTED_CONFIGURATION_VERSION
