"""Policy-3.3.1 German explicit self-exclusion safety regression."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

from player_triage.config import AppConfig, load_app_config
from player_triage.engine import TriageEngine
from player_triage.model import DeterministicFakeSemanticClassifier
from player_triage.semantic_evaluation import build_semantic_messages


@pytest.fixture(scope="module")
def config(app_root: Path) -> AppConfig:
    return load_app_config(app_root)


@pytest.fixture(scope="module")
def fixtures(app_root: Path) -> Mapping[str, list[Mapping[str, Any]]]:
    path = app_root / "tests" / "data" / "phase04_german_self_exclusion_fixtures.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    return document


def _message(config: AppConfig, case: Mapping[str, Any]):
    operational = dict(case)
    return build_semantic_messages(config, [operational])[str(case["case_id"])]


@pytest.mark.parametrize("index", range(7))
def test_german_positive_is_critical_terminal_and_never_calls_model(
    config: AppConfig,
    fixtures: Mapping[str, list[Mapping[str, Any]]],
    index: int,
) -> None:
    case = fixtures["positive"][index]
    provider = DeterministicFakeSemanticClassifier([])
    result = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    ).classify(_message(config, case))
    decision = result.decision
    assert provider.calls == [], case["case_id"]
    assert decision["category"] == "Responsible Gambling"
    assert decision["intent"] == "explicit_permanent_self_exclusion"
    assert decision["priority"] == "critical"
    assert decision["route"] == "specialist"
    assert decision["assigned_team"] == "Responsible Gambling"
    assert decision["human_review_required"] is True
    assert decision["model_called"] is False
    assert result.model_trace.gate_reason == "SAFETY_TERMINAL"


@pytest.mark.parametrize("index", range(6))
def test_german_negative_informational_or_attributed_is_not_activation(
    config: AppConfig,
    fixtures: Mapping[str, list[Mapping[str, Any]]],
    index: int,
) -> None:
    case = fixtures["negative"][index]
    result = TriageEngine.from_config(config).classify(_message(config, case))
    decision = result.decision
    assert decision["intent"] != "explicit_permanent_self_exclusion", case["case_id"]
    assert "self_exclusion_explicit" not in decision["risk_flags"]


def test_negated_request_with_independent_harm_still_routes_rg_without_model(
    config: AppConfig,
    fixtures: Mapping[str, list[Mapping[str, Any]]],
) -> None:
    case = fixtures["negative_with_independent_harm"][0]
    provider = DeterministicFakeSemanticClassifier([])
    result = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    ).classify(_message(config, case))
    assert provider.calls == []
    assert result.decision["category"] == "Responsible Gambling"
    assert result.decision["priority"] == "critical"
    assert result.decision["route"] == "specialist"
    assert result.decision["intent"] != "explicit_permanent_self_exclusion"


def test_policy_330_rollback_reproduces_failure_and_331_activation_fixes_it(
    app_root: Path,
    mutated_app_root: Callable[[], Path],
    fixtures: Mapping[str, list[Mapping[str, Any]]],
) -> None:
    root = mutated_app_root()
    archive_330 = root / "policy" / "config_versions" / "policy-3.3.0"
    archive_320 = root / "policy" / "config_versions" / "policy-3.2.0"
    (root / "policy" / "configuration_manifest.json").write_bytes(
        (archive_330 / "configuration_manifest.json").read_bytes()
    )
    (root / "policy" / "model_configuration.json").write_bytes(
        (archive_330 / "model_configuration.json").read_bytes()
    )
    # policy-3.3.0 inherited the policy-3.2.0 rules byte-for-byte; its
    # preserved manifest digest proves this is the evaluated predecessor.
    (root / "policy" / "policy_rules.json").write_bytes(
        (archive_320 / "policy_rules.json").read_bytes()
    )
    rolled = load_app_config(root, strict_version=False)
    active = load_app_config(app_root)
    # This form is the preserved M90 failure: policy-3.3.0 did not treat the
    # permanent gambling-block wording as deterministic explicit exclusion.
    case = fixtures["positive"][5]

    failed_provider = DeterministicFakeSemanticClassifier([])
    failed = TriageEngine.from_config(
        rolled, mode="local_model", semantic_classifier=failed_provider
    ).classify(_message(rolled, case))
    assert len(failed_provider.calls) == 1
    assert failed.model_trace.gate_reason == "ALLOWED"
    assert failed.decision["intent"] != "explicit_permanent_self_exclusion"

    fixed_provider = DeterministicFakeSemanticClassifier([])
    fixed = TriageEngine.from_config(
        active, mode="local_model", semantic_classifier=fixed_provider
    ).classify(_message(active, case))
    assert fixed_provider.calls == []
    assert fixed.model_trace.gate_reason == "SAFETY_TERMINAL"
    assert fixed.decision["intent"] == "explicit_permanent_self_exclusion"
