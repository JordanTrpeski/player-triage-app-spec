"""Semantic classifier implementations for Phase 04.

Only :class:`LocalModelSemanticClassifier` knows about ``llama_cpp`` and that
dependency is imported lazily after configuration and artifact integrity checks.
The module itself remains importable in a rules-only installation.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .contract import (
    ModelCandidate,
    ModelClassificationRequest,
    ModelResult,
    SemanticClassifier,
)
from .prompt import PROMPT_VERSION, build_messages, prompt_digest
from .validate import (
    CandidateJSONDecodeError,
    CandidatePolicyRejection,
    CandidateSchemaError,
    CandidateValidationError,
    CandidateValidator,
)
from .worker import (
    IsolatedModelWorker,
    ModelWorkerRuntimeError,
    ModelWorkerTimeout,
    WorkerSettings,
)


@dataclass(frozen=True, slots=True)
class RulesOnlySemanticClassifier:
    """Explicit no-call provider for the valid rules-only operating mode."""

    name: str = "rules_only"

    def classify(self, request: ModelClassificationRequest) -> ModelResult:
        return ModelResult(
            provider=self.name,
            called=False,
            error=None,
            fallback_reason="RULES_ONLY_MODE",
        )


@dataclass(frozen=True, slots=True)
class DisabledSemanticClassifier:
    """No-call provider used when local-model mode is administratively disabled."""

    name: str = "disabled"

    def classify(self, request: ModelClassificationRequest) -> ModelResult:
        return ModelResult(
            provider=self.name,
            called=False,
            error=None,
            fallback_reason="MODEL_DISABLED",
        )


FakeOutcome = ModelResult | ModelCandidate | str | Exception


@dataclass(slots=True)
class DeterministicFakeSemanticClassifier:
    """Scripted provider and call spy for deterministic safety/failure tests."""

    outcomes: Sequence[FakeOutcome]
    validator: CandidateValidator | None = None
    name: str = "deterministic_fake"
    calls: list[Mapping[str, object]] = field(default_factory=list, init=False)
    _index: int = field(default=0, init=False)

    def classify(self, request: ModelClassificationRequest) -> ModelResult:
        self.calls.append(request.sanitized_summary())
        if not self.outcomes:
            return ModelResult(
                provider=self.name,
                called=True,
                error="MODEL_RUNTIME_FAILURE",
                fallback_reason="MODEL_UNAVAILABLE",
            )
        outcome = self.outcomes[min(self._index, len(self.outcomes) - 1)]
        self._index += 1
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, ModelResult):
            return outcome
        if isinstance(outcome, ModelCandidate):
            return ModelResult(provider=self.name, called=True, candidate=outcome, valid=True)
        if self.validator is None:
            raise RuntimeError("fake string outcome requires a candidate validator")
        try:
            candidate = self.validator.parse(outcome)
        except CandidateValidationError as exc:
            return ModelResult(
                provider=self.name,
                called=True,
                error=exc.code,
                fallback_reason=_fallback_for_validation_error(exc),
            )
        return ModelResult(provider=self.name, called=True, candidate=candidate, valid=True)


@dataclass(frozen=True, slots=True)
class LocalModelSettings:
    """Resolved, host-local settings after governed configuration loading."""

    model_path: Path
    expected_sha256: str
    model_id: str
    revision: str
    runtime_version: str
    prompt_path: Path
    expected_prompt_version: str
    expected_prompt_sha256: str
    context_limit: int = 2048
    output_token_limit: int = 256
    timeout_seconds: float = 30.0
    temperature: float = 0.0
    max_schema_retries: int = 1


@dataclass(slots=True)
class LocalModelSemanticClassifier:
    """In-process, constrained-JSON llama.cpp adapter with fail-closed errors."""

    settings: LocalModelSettings
    validator: CandidateValidator
    name: str = "local_model"
    _runtime: Any = field(default=None, init=False, repr=False)
    _prompt_text: str | None = field(default=None, init=False, repr=False)
    _load_time_ms: float = field(default=0.0, init=False)
    _circuit_open: bool = field(default=False, init=False, repr=False)
    _worker_rss_bytes: int | None = field(default=None, init=False, repr=False)

    @property
    def load_time_ms(self) -> float:
        return self._load_time_ms

    @property
    def worker_rss_bytes(self) -> int | None:
        return self._worker_rss_bytes

    def close(self) -> None:
        worker = self._runtime
        if isinstance(worker, IsolatedModelWorker):
            worker.close()
        self._runtime = None

    def classify(self, request: ModelClassificationRequest) -> ModelResult:
        if self._circuit_open:
            return ModelResult(
                provider=self.name,
                called=False,
                error="MODEL_CIRCUIT_OPEN",
                fallback_reason="MODEL_UNAVAILABLE",
            )
        started = time.perf_counter()
        try:
            self._ensure_loaded()
        except CandidateValidationError as exc:
            self._circuit_open = True
            return ModelResult(
                provider=self.name,
                called=False,
                error=exc.code,
                fallback_reason=_fallback_for_validation_error(exc),
            )
        except Exception:
            self._circuit_open = True
            return ModelResult(
                provider=self.name,
                called=False,
                error="MODEL_INITIALIZATION_FAILURE",
                fallback_reason="MODEL_UNAVAILABLE",
            )

        retries = 0
        while True:
            try:
                raw = self._invoke(request, schema_retry=retries > 0)
                candidate = self.validator.parse(raw)
                return ModelResult(
                    provider=self.name,
                    called=True,
                    candidate=candidate,
                    valid=True,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    retries=retries,
                )
            except (CandidateJSONDecodeError, CandidateSchemaError) as exc:
                if retries < self.settings.max_schema_retries:
                    retries += 1
                    continue
                return ModelResult(
                    provider=self.name,
                    called=True,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    retries=retries,
                    error=exc.code,
                    fallback_reason="MODEL_SCHEMA_INVALID",
                )
            except CandidatePolicyRejection as exc:
                return ModelResult(
                    provider=self.name,
                    called=True,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    retries=retries,
                    error=exc.code,
                    fallback_reason="MODEL_SCHEMA_INVALID",
                )
            except ModelWorkerTimeout:
                self.close()
                return ModelResult(
                    provider=self.name,
                    called=True,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    retries=retries,
                    error="MODEL_TIMEOUT",
                    fallback_reason="MODEL_TIMEOUT",
                )
            except (ModelWorkerRuntimeError, Exception):
                self.close()
                return ModelResult(
                    provider=self.name,
                    called=True,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    retries=retries,
                    error="MODEL_RUNTIME_FAILURE",
                    fallback_reason="MODEL_UNAVAILABLE",
                )

    def _ensure_loaded(self) -> None:
        if self._runtime is not None:
            return
        settings = self.settings
        if not settings.model_path.is_file():
            raise FileNotFoundError("approved model artifact is unavailable")
        actual = _sha256_file(settings.model_path)
        if actual != settings.expected_sha256.lower():
            raise CandidatePolicyRejection("approved model artifact digest mismatch")
        if settings.expected_prompt_version != PROMPT_VERSION:
            raise CandidatePolicyRejection("classifier prompt version mismatch")
        prompt_text = settings.prompt_path.read_text(encoding="utf-8")
        if prompt_digest(prompt_text) != settings.expected_prompt_sha256.lower():
            raise CandidatePolicyRejection("classifier prompt digest mismatch")

        worker = IsolatedModelWorker(
            WorkerSettings(
                model_path=settings.model_path,
                runtime_version=settings.runtime_version,
                context_limit=settings.context_limit,
                output_token_limit=settings.output_token_limit,
                temperature=settings.temperature,
            ),
            startup_timeout_seconds=settings.timeout_seconds,
        )
        worker.start()
        self._runtime = worker
        self._prompt_text = prompt_text
        self._load_time_ms = worker.load_time_ms
        self._worker_rss_bytes = worker.rss_bytes

    def _invoke(self, request: ModelClassificationRequest, *, schema_retry: bool) -> str:
        assert isinstance(self._runtime, IsolatedModelWorker)
        assert self._prompt_text is not None
        messages = build_messages(self._prompt_text, request)
        if schema_retry:
            messages.append(
                {
                    "role": "system",
                    "content": "Return exactly one schema-valid JSON object; do not add prose.",
                }
            )

        outcome = self._runtime.infer(
            messages=messages,
            schema=self.validator.schema,
            timeout_seconds=self.settings.timeout_seconds,
        )
        self._worker_rss_bytes = outcome.rss_bytes
        return _extract_content(outcome.response)


def _extract_content(response: object) -> str:
    if not isinstance(response, Mapping):
        raise CandidateJSONDecodeError("runtime response envelope was invalid")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise CandidateJSONDecodeError("runtime response envelope was invalid")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise CandidateJSONDecodeError("runtime response envelope was invalid")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise CandidateJSONDecodeError("runtime response envelope was invalid")
    content = message.get("content")
    if not isinstance(content, str):
        raise CandidateJSONDecodeError("runtime response envelope was invalid")
    return content


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fallback_for_validation_error(error: CandidateValidationError) -> str:
    if isinstance(error, (CandidateJSONDecodeError, CandidateSchemaError, CandidatePolicyRejection)):
        return "MODEL_SCHEMA_INVALID"
    return "MODEL_UNAVAILABLE"


assert isinstance(RulesOnlySemanticClassifier(), SemanticClassifier)
assert isinstance(DisabledSemanticClassifier(), SemanticClassifier)
