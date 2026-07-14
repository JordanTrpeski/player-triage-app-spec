"""Immutable typed records used by ingestion, normalization, detection,
redaction, eligibility and linkage.

Records are split so that ``player_id`` — an authorized identifier — is only
carried by :class:`RawMessage` and remains inside the ingestion/linkage
context. Every downstream consumer receives :class:`IngestedMessage`, which
holds no player identifier and no raw subject/body — only the redacted
representation, detector metadata (counts + placeholders, never values) and
linkage results expressed as message IDs.

The intent is that a security review of any downstream module can rely on the
type system to guarantee player_id is not reachable from that module's
inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RawMessage:
    """Restricted record produced only by :mod:`player_triage.ingestion`.

    ``player_id`` is present here so linkage can group by player. Any module
    that receives a :class:`RawMessage` is inside the trusted ingestion/linkage
    boundary and must not export the ``player_id`` field into logs, outputs or
    audit events.
    """

    msg_id: str
    received_utc: datetime
    channel: str
    market: str
    language: str
    subject: str
    body: str
    player_id: str
    source_format: str  # "csv" or "xlsx"
    source_row: int

    def combined_text(self) -> str:
        """Concatenated subject + body used by detectors and normalization."""

        return f"{self.subject}\n{self.body}"


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    """Deterministically normalized text without any player identifier.

    ``normalized_text`` preserves language-specific characters and punctuation
    needed for semantic classification. ``detector_view`` is the case-insensitive
    version used only by detectors; it is *not* used as the model-input text.
    """

    msg_id: str
    received_utc: datetime
    channel: str
    market: str
    language: str
    normalized_subject: str
    normalized_body: str
    detector_view: str
    normalization_version: str


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Sanitized detector outcome — never contains matched sensitive values."""

    detector_id: str
    count: int
    replacement_placeholder: str
    risk_flags: tuple[str, ...]
    status: str  # "detected" | "clear" | "uncertain"

    def is_detected(self) -> bool:
        return self.status == "detected" and self.count > 0


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Result of applying redaction to a normalized message.

    ``redacted_text`` is safe to hand to a model provided the linked
    :class:`EligibilityDecision` allows model use. ``redaction_uncertain`` is
    set when any detector reported ``status == "uncertain"``.
    """

    redacted_text: str
    detections: tuple[DetectionResult, ...]
    redaction_uncertain: bool
    prompt_injection_detected: bool


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """Ingestion/redaction-level model eligibility decision.

    Values are intentionally *not* the fine-grained
    ``policy/controlled_vocabularies.json → model_eligibility`` catalogue —
    those pertain to the whole downstream decision and combine ingestion signal
    with deterministic policy and attachment state. Phase 02 only knows the
    ingestion-level view.
    """

    state: str  # one of: eligible, bypass_sensitive, bypass_attachment,
    #                     bypass_untrusted_input, redaction_uncertain, invalid_input
    reason: str | None
    attachment_received: bool
    attachment_referenced: bool
    identity_document_referenced: bool


@dataclass(frozen=True, slots=True)
class LinkageResult:
    """Per-message linkage output. Uses message IDs only; no player ID."""

    msg_id: str
    related_message_ids: tuple[str, ...]
    first_contact_message_id: str | None
    previous_contact_count: int
    linkage_rule_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IngestedMessage:
    """Public downstream record with no player identifier and no raw text."""

    msg_id: str
    received_utc: datetime
    channel: str
    market: str
    language: str
    normalization_version: str
    redacted_text: str
    detections: tuple[DetectionResult, ...]
    eligibility: EligibilityDecision
    linkage: LinkageResult
    market_overlay_codes: tuple[str, ...]
    market_framework_status: str

    def risk_flags(self) -> tuple[str, ...]:
        """Deduplicated union of risk flags across detections."""

        seen: dict[str, None] = {}
        for detection in self.detections:
            for flag in detection.risk_flags:
                seen.setdefault(flag, None)
        return tuple(seen.keys())


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Sanitized ingestion/validation issue for later reporting."""

    msg_id: str | None
    source_row: int | None
    code: str
    detail: str  # sanitized: no subject/body/player_id/sensitive values
