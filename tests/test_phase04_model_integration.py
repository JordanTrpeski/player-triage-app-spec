"""Phase 04 model-call gate, aggregation, fallback and audit tests."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from player_triage.config import AppConfig, load_app_config
from player_triage.engine import TriageEngine
from player_triage.model import (
    CandidateValidator,
    DeterministicFakeSemanticClassifier,
    ModelCandidate,
    ModelClassificationRequest,
    ModelResult,
)
from player_triage.pipeline import ingest
from player_triage.records import EligibilityDecision, IngestedMessage


@pytest.fixture(scope="module")
def config(app_root: Path) -> AppConfig:
    return load_app_config(app_root)


@pytest.fixture(scope="module")
def messages(config: AppConfig) -> dict[str, IngestedMessage]:
    return {message.msg_id: message for message in ingest(config)}


def _rules_candidate(config: AppConfig, message: IngestedMessage) -> ModelCandidate:
    decision = TriageEngine.from_config(config).classify(message).decision
    return ModelCandidate(
        category=str(decision["category"]),
        intent=str(decision["intent"]),
        secondary_intents=(),
        signals=(),
        complaint_indicator="none",
        ambiguity="clear",
    )


def _eligible_copy(
    message: IngestedMessage,
    *,
    state: str,
    reason: str | None,
    text: str | None = None,
    attachment_received: bool = False,
) -> IngestedMessage:
    eligibility = EligibilityDecision(
        state=state,
        reason=reason,
        attachment_received=attachment_received,
        attachment_referenced=message.eligibility.attachment_referenced,
        identity_document_referenced=message.eligibility.identity_document_referenced,
    )
    return replace(
        message,
        redacted_text=message.redacted_text if text is None else text,
        eligibility=eligibility,
    )


def test_eligible_message_calls_spy_once(
    config: AppConfig, messages: dict[str, IngestedMessage]
) -> None:
    message = messages["M01"]
    provider = DeterministicFakeSemanticClassifier([_rules_candidate(config, message)])
    result = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    ).classify(message)
    assert len(provider.calls) == 1
    assert result.decision["model_called"] is True
    assert result.decision["decision_basis"] == "model_assisted"
    assert result.model_trace.gate_reason == "ALLOWED"
    assert result.model_trace.agreement is True


def test_request_contract_has_no_raw_or_player_identity_fields() -> None:
    names = {item.name for item in fields(ModelClassificationRequest)}
    assert names.isdisjoint({"raw_text", "subject", "body", "player_id"})


def test_zero_calls_for_supplied_sensitive_injection_and_safety_terminals(
    config: AppConfig, messages: dict[str, IngestedMessage]
) -> None:
    provider = DeterministicFakeSemanticClassifier([])
    engine = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    )
    for message_id in ("M07", "M11", "M15", "M18", "M21", "M23", "M28", "M36"):
        result = engine.classify(messages[message_id])
        assert result.decision["model_called"] is False, message_id
    assert provider.calls == []


@pytest.mark.parametrize(
    ("state", "reason", "attachment", "expected_gate"),
    [
        ("bypass_sensitive", "sensitive_payment_or_authentication_data", False, "SENSITIVE_BYPASS"),
        ("bypass_untrusted_input", "prompt_injection_detected", False, "PROMPT_INJECTION_BYPASS"),
        ("bypass_attachment", "attachment_received_body_insufficient", True, "ATTACHMENT_BYPASS"),
        ("redaction_uncertain", "redaction_uncertain", False, "REDACTION_UNCERTAIN"),
        ("invalid_input", "empty_message_body", False, "INPUT_INVALID"),
    ],
)
def test_zero_calls_for_every_ingestion_bypass_and_state_is_preserved(
    config: AppConfig,
    messages: dict[str, IngestedMessage],
    state: str,
    reason: str,
    attachment: bool,
    expected_gate: str,
) -> None:
    source = messages["M01"]
    message = _eligible_copy(
        source,
        state=state,
        reason=reason,
        text="" if state == "invalid_input" else None,
        attachment_received=attachment,
    )
    provider = DeterministicFakeSemanticClassifier([])
    result = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    ).classify(message)
    assert provider.calls == []
    assert result.decision["model_called"] is False
    assert result.model_trace.gate_reason == expected_gate
    assert str(result.decision["model_eligibility"]).startswith("bypass_")
    assert result.decision["model_bypass_reason"] is not None


def test_kill_switch_forces_rules_only_without_adapter_call(
    config: AppConfig, messages: dict[str, IngestedMessage]
) -> None:
    provider = DeterministicFakeSemanticClassifier([])
    result = TriageEngine.from_config(
        config,
        mode="local_model",
        semantic_classifier=provider,
        kill_switch=True,
    ).classify(messages["M01"])
    assert provider.calls == []
    assert result.decision["model_called"] is False
    assert result.model_trace.gate_reason == "KILL_SWITCH_ACTIVE"
    assert result.decision["processing_status"] == "classified"


def test_model_disagreement_keeps_deterministic_signals_and_routing_authority(
    config: AppConfig, messages: dict[str, IngestedMessage]
) -> None:
    message = messages["M29"]
    candidate = ModelCandidate(
        category="General",
        intent="compliment_no_action",
        secondary_intents=(),
        signals=("no_action_requested",),
        complaint_indicator="none",
        ambiguity="clear",
    )
    provider = DeterministicFakeSemanticClassifier([candidate])
    result = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    ).classify(message)
    decision = result.decision
    assert result.model_trace.agreement is False
    assert "attachment_referenced" in decision["risk_flags"]
    assert "no_action_requested" in decision["risk_flags"]
    assert decision["priority"] in config.vocab.priorities
    assert decision["route"] in config.vocab.routes
    assert decision["assigned_team"] in config.vocab.teams
    assert result.schema_valid and not result.semantic_violations


@pytest.mark.parametrize("ambiguity", ["some_ambiguity", "insufficient_information"])
def test_ambiguous_candidate_falls_to_human_manual_review(
    config: AppConfig,
    messages: dict[str, IngestedMessage],
    ambiguity: str,
) -> None:
    message = messages["M12"]
    candidate = replace(_rules_candidate(config, message), ambiguity=ambiguity)
    provider = DeterministicFakeSemanticClassifier([candidate])
    result = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    ).classify(message)
    assert result.decision["model_called"] is True
    assert result.decision["processing_status"] == "provisional_fallback"
    assert result.decision["route"] == "human"
    assert result.decision["human_review_required"] is True
    assert result.decision["auto_response_template_id"] is None
    assert result.model_trace.fallback_reason == "NO_CLASSIFICATION_CANDIDATE"


@pytest.mark.parametrize(
    ("outcome", "fallback"),
    [
        (ModelResult("fake", True, error="MODEL_TIMEOUT", fallback_reason="MODEL_TIMEOUT"), "MODEL_TIMEOUT"),
        (ModelResult("fake", False, error="MODEL_INITIALIZATION_FAILURE", fallback_reason="MODEL_UNAVAILABLE"), "MODEL_UNAVAILABLE"),
        (ModelResult("fake", True, error="MODEL_RUNTIME_FAILURE", fallback_reason="MODEL_UNAVAILABLE"), "MODEL_UNAVAILABLE"),
        (ModelResult("fake", True, error="MODEL_SCHEMA_INVALID", fallback_reason="MODEL_SCHEMA_INVALID"), "MODEL_SCHEMA_INVALID"),
    ],
)
def test_model_failures_continue_with_deterministic_manual_result(
    config: AppConfig,
    messages: dict[str, IngestedMessage],
    outcome: ModelResult,
    fallback: str,
) -> None:
    provider = DeterministicFakeSemanticClassifier([outcome])
    engine = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    )
    result = engine.classify(messages["M01"])
    assert result.decision["processing_status"] == "provisional_fallback"
    assert result.decision["route"] == "human"
    assert result.model_trace.fallback_reason == fallback
    event = engine.build_model_failure_audit_event(result)
    assert event is not None
    serialized = json.dumps(event)
    assert messages["M01"].redacted_text not in serialized
    schema_id = config.schema_registry.ids["audit_event_schema.json"]
    config.schema_registry.validate(schema_id, event, component_hint="model_failure_audit")


def test_malformed_json_and_extra_field_fail_without_batch_abort(
    config: AppConfig, messages: dict[str, IngestedMessage]
) -> None:
    validator = CandidateValidator.from_config(config)
    valid = _rules_candidate(config, messages["M02"]).as_dict()
    invalid_extra = dict(valid, forbidden_extra=True)
    provider = DeterministicFakeSemanticClassifier(
        ["not-json", json.dumps(invalid_extra)], validator=validator
    )
    engine = TriageEngine.from_config(
        config, mode="local_model", semantic_classifier=provider
    )
    first = engine.classify(messages["M01"])
    second = engine.classify(messages["M02"])
    assert first.model_trace.fallback_reason == "MODEL_SCHEMA_INVALID"
    assert second.model_trace.fallback_reason == "MODEL_SCHEMA_INVALID"
    assert first.decision["route"] == second.decision["route"] == "human"
    assert len(provider.calls) == 2
