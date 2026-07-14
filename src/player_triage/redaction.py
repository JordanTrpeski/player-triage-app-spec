"""Deterministic, idempotent redaction driven by :mod:`player_triage.detection`.

The redactor consumes the immutable :class:`~player_triage.detection.DetectionOutcome`
and rewrites the input text so that every matched span is replaced by the
policy-approved placeholder. Because placeholders are wrapped in square
brackets and contain only uppercase letters/underscores (`[PAYMENT_CARD_REMOVED]`,
`[AUTH_SECRET_PURGED]`, …), none of the detectors match a placeholder and
``redact(redact(text)) == redact(text)`` is guaranteed. That invariant is
enforced by a unit test.

The public :func:`redact` also detects three ingestion-level signals that the
eligibility gate uses:

* ``attachment_referenced``: the text mentions an attachment/screenshot/photo
  without an attachment metadata record.
* ``identity_document_referenced``: the text mentions an identity document
  type (passport, aadhaar, driving licence, national id) *without* an
  IDENTITY_DOC_NUMBER match.

These reference detectors intentionally do NOT strip the referenced words —
they only mark the message so downstream policy can route appropriately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Mapping

from .detection import DetectionEngine, DetectionOutcome
from .records import RedactionResult

_ATTACHMENT_REFERENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:attach(?:ed|ment)s?|screenshots?|screen ?shots?|photos?|"
    r"pictures?|videos?|recordings?|receipts?)\b"
)
_IDENTITY_REFERENCE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:passport|aadhaar|national\s+id|driving\s+licen[cs]e|"
    r"identity\s+card)\b"
)


@dataclass(frozen=True, slots=True)
class ReferenceFlags:
    attachment_referenced: bool
    identity_document_referenced: bool


def apply_redaction(text: str, outcome: DetectionOutcome) -> str:
    """Rewrite ``text`` in place using the ordered matches from ``outcome``."""

    if not outcome.matches:
        return text

    # Replace from right to left so span offsets remain valid.
    replaced = text
    for match in reversed(outcome.matches):
        replaced = replaced[: match.start] + match.replacement + replaced[match.end :]
    return replaced


def detect_reference_flags(text: str, outcome: DetectionOutcome) -> ReferenceFlags:
    id_doc_number_hit = any(
        detection.detector_id == "IDENTITY_DOC_NUMBER"
        and detection.is_detected()
        for detection in outcome.detections
    )
    identity_document_referenced = (
        bool(_IDENTITY_REFERENCE_RE.search(text)) and not id_doc_number_hit
    )
    # When the message is centred on an identity document upload, the "photo"
    # / "file" tokens describe the identity document itself. Treat that as an
    # identity-document reference only; do not double-count as an unrelated
    # attachment reference.
    attachment_referenced = (
        bool(_ATTACHMENT_REFERENCE_RE.search(text))
        and not identity_document_referenced
    )
    return ReferenceFlags(
        attachment_referenced=attachment_referenced,
        identity_document_referenced=identity_document_referenced,
    )


def redact(text: str, engine: DetectionEngine) -> RedactionResult:
    """Run detection followed by redaction over ``text`` in one call."""

    outcome = engine.scan(text)
    redacted_text = apply_redaction(text, outcome)
    return RedactionResult(
        redacted_text=redacted_text,
        detections=outcome.detections,
        redaction_uncertain=outcome.uncertain,
        prompt_injection_detected=outcome.prompt_injection_detected,
    )


def is_idempotent(text: str, engine: DetectionEngine) -> bool:
    """Assert ``redact(redact(text)) == redact(text)`` in one call."""

    once = redact(text, engine).redacted_text
    twice = redact(once, engine).redacted_text
    return once == twice


__all__ = [
    "ReferenceFlags",
    "apply_redaction",
    "detect_reference_flags",
    "redact",
    "is_idempotent",
]
