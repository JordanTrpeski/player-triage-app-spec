"""Phase 04 strict candidate validation and provider-contract tests."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pytest

from player_triage.config import AppConfig, load_app_config
from player_triage.model import (
    CandidateJSONDecodeError,
    CandidatePolicyRejection,
    CandidateSchemaError,
    CandidateValidator,
    DeterministicFakeSemanticClassifier,
    DisabledSemanticClassifier,
    LocalModelSemanticClassifier,
    LocalModelSettings,
    ModelClassificationRequest,
    RulesOnlySemanticClassifier,
)
from player_triage.model.prompt import PROMPT_VERSION, prompt_digest
from player_triage.model.worker import (
    IsolatedModelWorker,
    ModelWorkerRuntimeError,
    ModelWorkerTimeout,
    WorkerSettings,
    hanging_test_worker,
)


@pytest.fixture(scope="module")
def config(app_root: Path) -> AppConfig:
    return load_app_config(app_root)


@pytest.fixture(scope="module")
def validator(config: AppConfig) -> CandidateValidator:
    return CandidateValidator.from_config(config)


def _valid_document(config: AppConfig) -> dict[str, Any]:
    return {
        "category": config.vocab.categories[0],
        "intent": config.vocab.intents[0],
        "secondary_intents": [config.vocab.intents[1]],
        "signals": ["account_specific"],
        "complaint_indicator": "none",
        "ambiguity": "clear",
    }


def _request(config: AppConfig) -> ModelClassificationRequest:
    return ModelClassificationRequest(
        message_id="SYNTHETIC-01",
        redacted_text="A synthetic, already-redacted classification request.",
        language="en",
        categories=config.vocab.categories,
        intents=config.vocab.intents,
    )


def test_candidate_accepts_exact_schema(
    config: AppConfig, validator: CandidateValidator
) -> None:
    candidate = validator.validate(_valid_document(config))
    assert candidate.category == config.vocab.categories[0]
    assert candidate.intent == config.vocab.intents[0]


@pytest.mark.parametrize(
    ("mutation", "error_type"),
    [
        (lambda d: d.update(extra_field=True), CandidateSchemaError),
        (lambda d: d.pop("intent"), CandidateSchemaError),
        (lambda d: d.update(intent="not_an_approved_intent"), CandidateSchemaError),
        (lambda d: d.update(secondary_intents="wrong_type"), CandidateSchemaError),
        (lambda d: d.update(complaint_indicator=7), CandidateSchemaError),
    ],
)
def test_candidate_rejects_schema_defects_without_value_leakage(
    config: AppConfig,
    validator: CandidateValidator,
    mutation: Any,
    error_type: type[Exception],
) -> None:
    document = _valid_document(config)
    mutation(document)
    marker = "not_an_approved_intent"
    with pytest.raises(error_type) as excinfo:
        validator.validate(document)
    assert marker not in str(excinfo.value)
    assert json.dumps(document) not in str(excinfo.value)


def test_candidate_rejects_malformed_and_empty_json(
    validator: CandidateValidator,
) -> None:
    for raw in ("", "not-json", "{"):
        with pytest.raises(CandidateJSONDecodeError) as excinfo:
            validator.parse(raw)
        if raw:
            assert raw not in str(excinfo.value)


def test_candidate_rejects_primary_repeated_as_secondary(
    config: AppConfig, validator: CandidateValidator
) -> None:
    document = _valid_document(config)
    document["secondary_intents"] = [document["intent"]]
    with pytest.raises(CandidatePolicyRejection):
        validator.validate(document)


def test_candidate_rejects_model_asserted_safety_signal(
    config: AppConfig, validator: CandidateValidator
) -> None:
    document = _valid_document(config)
    document["signals"] = ["prompt_injection_detected"]
    with pytest.raises(CandidatePolicyRejection):
        validator.validate(document)


def test_rules_only_and_disabled_never_call_a_runtime(config: AppConfig) -> None:
    request = _request(config)
    rules = RulesOnlySemanticClassifier().classify(request)
    disabled = DisabledSemanticClassifier().classify(request)
    assert rules.called is False and rules.candidate is None
    assert disabled.called is False and disabled.candidate is None


def test_deterministic_fake_is_a_sanitized_call_spy(
    config: AppConfig, validator: CandidateValidator
) -> None:
    raw = json.dumps(_valid_document(config))
    provider = DeterministicFakeSemanticClassifier([raw], validator=validator)
    result = provider.classify(_request(config))
    assert result.valid and result.called
    assert len(provider.calls) == 1
    assert "redacted_text" not in provider.calls[0]


def _settings(
    model_path: Path,
    prompt_path: Path,
    *,
    model_digest: str,
    prompt_sha256: str,
) -> LocalModelSettings:
    return LocalModelSettings(
        model_path=model_path,
        expected_sha256=model_digest,
        model_id="synthetic/local-model",
        revision="0" * 40,
        runtime_version="0.3.34",
        prompt_path=prompt_path,
        expected_prompt_version=PROMPT_VERSION,
        expected_prompt_sha256=prompt_sha256,
        timeout_seconds=0.1,
    )


def test_local_provider_missing_model_fails_closed_without_call(
    config: AppConfig, validator: CandidateValidator, tmp_path: Path
) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("{{redacted_message}}", encoding="utf-8")
    provider = LocalModelSemanticClassifier(
        _settings(
            tmp_path / "missing.gguf",
            prompt_path,
            model_digest="0" * 64,
            prompt_sha256=prompt_digest("{{redacted_message}}"),
        ),
        validator,
    )
    result = provider.classify(_request(config))
    assert result.called is False
    assert result.error == "MODEL_INITIALIZATION_FAILURE"
    assert result.fallback_reason == "MODEL_UNAVAILABLE"


def test_local_provider_wrong_digest_fails_before_runtime_import(
    config: AppConfig,
    validator: CandidateValidator,
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"not-a-real-model")
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("{{redacted_message}}", encoding="utf-8")
    provider = LocalModelSemanticClassifier(
        _settings(
            model_path,
            prompt_path,
            model_digest="0" * 64,
            prompt_sha256=prompt_digest("{{redacted_message}}"),
        ),
        validator,
    )
    result = provider.classify(_request(config))
    assert result.called is False
    assert result.error == "MODEL_POLICY_REJECTED"


def test_optional_runtime_missing_is_sanitized(
    config: AppConfig,
    validator: CandidateValidator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"synthetic-model")
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("{{redacted_message}}", encoding="utf-8")
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()

    def missing_runtime(self: IsolatedModelWorker) -> None:
        raise ModelWorkerRuntimeError("optional runtime unavailable")

    monkeypatch.setattr(IsolatedModelWorker, "start", missing_runtime)
    provider = LocalModelSemanticClassifier(
        _settings(
            model_path,
            prompt_path,
            model_digest=digest,
            prompt_sha256=prompt_digest("{{redacted_message}}"),
        ),
        validator,
    )
    result = provider.classify(_request(config))
    assert result.called is False
    assert result.error == "MODEL_INITIALIZATION_FAILURE"
    assert "llama" not in str(result)


def test_isolated_worker_timeout_terminates_native_process(tmp_path: Path) -> None:
    worker = IsolatedModelWorker(
        WorkerSettings(
            model_path=tmp_path / "unused.gguf",
            runtime_version="0.3.34",
            context_limit=512,
            output_token_limit=64,
            temperature=0.0,
        ),
        startup_timeout_seconds=5.0,
        worker_target=hanging_test_worker,
    )
    started = time.perf_counter()
    worker.start()
    assert worker.is_alive
    with pytest.raises(ModelWorkerTimeout):
        worker.infer(messages=[], schema={}, timeout_seconds=0.2)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0
    assert not worker.is_alive


def test_schema_only_retry_is_bounded_to_one(
    config: AppConfig,
    validator: CandidateValidator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("{{redacted_message}}", encoding="utf-8")
    provider = LocalModelSemanticClassifier(
        _settings(
            tmp_path / "unused.gguf",
            prompt_path,
            model_digest="0" * 64,
            prompt_sha256=prompt_digest("{{redacted_message}}"),
        ),
        validator,
    )
    calls: list[bool] = []

    monkeypatch.setattr(LocalModelSemanticClassifier, "_ensure_loaded", lambda self: None)

    def invalid(self: LocalModelSemanticClassifier, request: object, *, schema_retry: bool) -> str:
        calls.append(schema_retry)
        return "not-json"

    monkeypatch.setattr(LocalModelSemanticClassifier, "_invoke", invalid)
    result = provider.classify(_request(config))
    assert calls == [False, True]
    assert result.retries == 1
    assert result.error == "MODEL_JSON_INVALID"
    assert result.fallback_reason == "MODEL_SCHEMA_INVALID"
