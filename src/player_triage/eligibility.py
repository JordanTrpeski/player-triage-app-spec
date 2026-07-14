"""Ingestion/redaction-level model eligibility gate.

Phase 02 only produces the eligibility signal that ingestion and redaction can
observe. The downstream deterministic policy engine (Phase 03) combines this
with market overlays, attachment state and rule-based safety checks to arrive
at the final :class:`~player_triage.records.EligibilityDecision.state` value
in the controlled vocabulary. To keep the two layers cleanly separated, the
states emitted here are the six the phase brief lists:

* ``eligible``
* ``bypass_sensitive``
* ``bypass_attachment``
* ``bypass_untrusted_input``
* ``redaction_uncertain``
* ``invalid_input``

Precedence when multiple signals fire simultaneously:

1. ``invalid_input`` (no usable text at all).
2. ``redaction_uncertain`` (detector flagged uncertainty).
3. ``bypass_untrusted_input`` (prompt injection detected).
4. ``bypass_sensitive`` (PAN or CVV or authentication-secret detected).
5. ``bypass_attachment`` (attachment received *and* body insufficient).
6. ``eligible`` otherwise.
"""

from __future__ import annotations

from typing import Final

from .records import DetectionResult, EligibilityDecision, NormalizedMessage
from .redaction import ReferenceFlags


_BODY_SUFFICIENT_MINIMUM: Final[int] = 32
_SENSITIVE_DETECTOR_IDS: Final[frozenset[str]] = frozenset(
    {"AUTH_SECRET", "CVV", "PAN"}
)


def _sensitive_hit(detections: tuple[DetectionResult, ...]) -> DetectionResult | None:
    for detection in detections:
        if detection.detector_id in _SENSITIVE_DETECTOR_IDS and detection.is_detected():
            return detection
    return None


def _sensitive_reason(detection: DetectionResult) -> str:
    if detection.detector_id == "PAN":
        return "pan_and_cvv_detected"
    if detection.detector_id == "CVV":
        return "pan_and_cvv_detected"
    if detection.detector_id == "AUTH_SECRET":
        return "sensitive_payment_or_authentication_data"
    return "sensitive_payment_or_authentication_data"


def decide(
    normalized: NormalizedMessage,
    detections: tuple[DetectionResult, ...],
    prompt_injection_detected: bool,
    redaction_uncertain: bool,
    reference_flags: ReferenceFlags,
    attachment_received: bool,
) -> EligibilityDecision:
    body_len = len(normalized.normalized_body.strip())
    subject_len = len(normalized.normalized_subject.strip())

    if subject_len == 0 and body_len == 0:
        return EligibilityDecision(
            state="invalid_input",
            reason="empty_message_body",
            attachment_received=attachment_received,
            attachment_referenced=reference_flags.attachment_referenced,
            identity_document_referenced=reference_flags.identity_document_referenced,
        )

    if redaction_uncertain:
        return EligibilityDecision(
            state="redaction_uncertain",
            reason="redaction_uncertain",
            attachment_received=attachment_received,
            attachment_referenced=reference_flags.attachment_referenced,
            identity_document_referenced=reference_flags.identity_document_referenced,
        )

    if prompt_injection_detected:
        return EligibilityDecision(
            state="bypass_untrusted_input",
            reason="prompt_injection_detected",
            attachment_received=attachment_received,
            attachment_referenced=reference_flags.attachment_referenced,
            identity_document_referenced=reference_flags.identity_document_referenced,
        )

    sensitive = _sensitive_hit(detections)
    if sensitive is not None:
        return EligibilityDecision(
            state="bypass_sensitive",
            reason=_sensitive_reason(sensitive),
            attachment_received=attachment_received,
            attachment_referenced=reference_flags.attachment_referenced,
            identity_document_referenced=reference_flags.identity_document_referenced,
        )

    if attachment_received and body_len < _BODY_SUFFICIENT_MINIMUM:
        return EligibilityDecision(
            state="bypass_attachment",
            reason="attachment_received_body_insufficient",
            attachment_received=attachment_received,
            attachment_referenced=reference_flags.attachment_referenced,
            identity_document_referenced=reference_flags.identity_document_referenced,
        )

    return EligibilityDecision(
        state="eligible",
        reason=None,
        attachment_received=attachment_received,
        attachment_referenced=reference_flags.attachment_referenced,
        identity_document_referenced=reference_flags.identity_document_referenced,
    )
