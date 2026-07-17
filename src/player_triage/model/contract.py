"""Provider-independent semantic-classifier contract (Phase 04).

The request carries only already-approved, redacted, model-eligible text and the
controlled category/intent catalogues. It never carries raw PAN/CVV,
authentication secrets, player identifiers, identity-document values, attachment
bytes, source-system identifiers, or prompt-injection/high-risk cases (those are
gated out by the engine before a request is ever built).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ModelClassificationRequest:
    """Everything the local model is allowed to see. Redacted, eligible text only."""

    message_id: str
    redacted_text: str
    language: str
    categories: tuple[str, ...]
    intents: tuple[str, ...]

    def sanitized_summary(self) -> Mapping[str, object]:
        """Log-safe view: never includes the redacted text itself."""

        return {
            "message_id": self.message_id,
            "language": self.language,
            "text_length": len(self.redacted_text),
            "category_options": len(self.categories),
            "intent_options": len(self.intents),
        }


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    """A proposal conforming to ``schemas/model_candidate_schema.json``.

    Semantic proposal only — it never contains priority, route, team,
    eligibility, or any decision/action field.
    """

    category: str
    intent: str
    secondary_intents: tuple[str, ...]
    signals: tuple[str, ...]
    complaint_indicator: str
    ambiguity: str

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "intent": self.intent,
            "secondary_intents": list(self.secondary_intents),
            "signals": list(self.signals),
            "complaint_indicator": self.complaint_indicator,
            "ambiguity": self.ambiguity,
        }


@dataclass(frozen=True, slots=True)
class ModelResult:
    """Outcome of a classify() call.

    ``called`` is False when the provider abstained (rules-only/disabled) without
    invoking any model runtime. ``candidate`` is None on abstain or on an
    unrecoverable failure; ``error`` is a sanitized failure code, never raw
    content.
    """

    provider: str
    called: bool
    candidate: ModelCandidate | None = None
    valid: bool = False
    latency_ms: float = 0.0
    retries: int = 0
    error: str | None = None
    fallback_reason: str | None = None


@runtime_checkable
class SemanticClassifier(Protocol):
    """Provider interface. Implementations must never mutate the request."""

    name: str

    def classify(self, request: ModelClassificationRequest) -> ModelResult:
        ...


class ModelUnavailable(Exception):
    """Sanitized: raised when a local model cannot be loaded or run.

    The message must never contain raw player text or sensitive values.
    """
