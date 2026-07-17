"""Strict validation for local semantic-classifier candidates.

The validator deliberately exposes only failure classes and schema locations.
It never includes the model response, an offending value, or player text in an
exception message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from ..config import AppConfig
from .contract import ModelCandidate

_SCHEMA_FILE = "model_candidate_schema.json"

# These signals describe a condition that the deterministic pre-model gate must
# have intercepted. Accepting one from a model would let the semantic component
# invent a safety fact, so it is a policy rejection rather than a schema repair.
_MODEL_FORBIDDEN_SIGNALS = frozenset(
    {
        "attachment_received",
        "cvv_exposed",
        "full_pan_exposed",
        "prompt_injection_detected",
        "redaction_uncertain",
        "self_exclusion_explicit",
        "self_harm_signal",
        "sensitive_authentication_data",
        "underage_reported",
    }
)


class CandidateValidationError(Exception):
    """Base class for sanitized candidate failures."""

    code = "MODEL_CANDIDATE_INVALID"


class CandidateJSONDecodeError(CandidateValidationError):
    """The runtime did not return one JSON object."""

    code = "MODEL_JSON_INVALID"


class CandidateSchemaError(CandidateValidationError):
    """The decoded object did not conform to the candidate schema."""

    code = "MODEL_SCHEMA_INVALID"


class CandidatePolicyRejection(CandidateValidationError):
    """The schema-valid candidate conflicts with deterministic policy."""

    code = "MODEL_POLICY_REJECTED"


@dataclass(frozen=True, slots=True)
class CandidateValidator:
    """Draft 2020-12 schema and policy-compatibility validator."""

    schema: Mapping[str, Any]
    categories: frozenset[str]
    intents: frozenset[str]
    signals: frozenset[str]

    @classmethod
    def from_config(cls, config: AppConfig) -> "CandidateValidator":
        schema_id = config.schema_registry.ids[_SCHEMA_FILE]
        schema = config.schema_registry.schemas[schema_id]
        return cls(
            schema=schema,
            categories=frozenset(config.vocab.categories),
            intents=frozenset(config.vocab.intents),
            signals=frozenset(config.vocab.risk_flags),
        )

    def parse(self, raw_response: str) -> ModelCandidate:
        """Decode and validate a raw runtime response without value leakage."""

        if not raw_response.strip():
            raise CandidateJSONDecodeError("model response was empty")
        try:
            document = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError) as exc:
            raise CandidateJSONDecodeError("model response was not valid JSON") from exc
        return self.validate(document)

    def validate(self, document: object) -> ModelCandidate:
        validator = Draft202012Validator(dict(self.schema))
        errors = sorted(
            validator.iter_errors(document),
            key=lambda error: (list(error.absolute_path), error.validator or ""),
        )
        if errors:
            first = errors[0]
            location = "/".join(str(part) for part in first.absolute_path) or "<root>"
            keyword = first.validator or "unknown"
            raise CandidateSchemaError(
                f"candidate schema validation failed at {location} ({keyword})"
            )
        if not isinstance(document, Mapping):  # guarded by schema; keeps typing honest
            raise CandidateSchemaError("candidate schema validation failed at <root> (type)")

        category = document["category"]
        intent = document["intent"]
        secondary = tuple(document["secondary_intents"])
        signals = tuple(document["signals"])
        complaint = document["complaint_indicator"]
        ambiguity = document["ambiguity"]
        if not isinstance(category, str) or category not in self.categories:
            raise CandidatePolicyRejection("candidate category is not policy-approved")
        if not isinstance(intent, str) or intent not in self.intents:
            raise CandidatePolicyRejection("candidate intent is not policy-approved")
        if any(not isinstance(item, str) or item not in self.intents for item in secondary):
            raise CandidatePolicyRejection("candidate secondary intent is not policy-approved")
        if intent in secondary:
            raise CandidatePolicyRejection("candidate repeats the primary intent as secondary")
        if any(not isinstance(item, str) or item not in self.signals for item in signals):
            raise CandidatePolicyRejection("candidate signal is not policy-approved")
        if _MODEL_FORBIDDEN_SIGNALS.intersection(signals):
            raise CandidatePolicyRejection("candidate asserted a deterministic safety signal")
        assert isinstance(complaint, str)
        assert isinstance(ambiguity, str)
        return ModelCandidate(
            category=category,
            intent=intent,
            secondary_intents=secondary,
            signals=signals,
            complaint_indicator=complaint,
            ambiguity=ambiguity,
        )
