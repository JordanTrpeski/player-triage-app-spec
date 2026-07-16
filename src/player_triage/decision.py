"""Assembly of the final schema-conforming triage decision object.

The decision object contains exactly the fields required by
``schemas/output_schema.json`` (which forbids additional properties). Stage and
rule provenance is *not* part of this object — it is carried separately by the
:class:`~player_triage.working.WorkingDecision.trace` and surfaced through the
CLI and tests.
"""

from __future__ import annotations

from typing import Any

from .records import IngestedMessage
from .routing import load_routing_map
from .working import WorkingDecision


def assemble_decision(
    message: IngestedMessage,
    decision: WorkingDecision,
    *,
    market_applicability_note: str | None,
    short_rationale: str,
    processing_status: str = "classified",
) -> dict[str, Any]:
    """Build the output-schema dict for a fully-resolved decision."""

    primary_intent = decision.intent
    secondary_intents = [
        intent
        for intent in decision.secondary_intents
        if intent != primary_intent
    ]

    return {
        "message_id": message.msg_id,
        "received_utc": message.received_utc.isoformat().replace("+00:00", "Z"),
        "channel": message.channel,
        "market": message.market,
        "language": message.language,
        "processing_status": processing_status,
        "category": decision.category,
        "intent": primary_intent,
        "secondary_intents": secondary_intents,
        "priority": decision.priority,
        "route": decision.route,
        "assigned_team": decision.assigned_team,
        "secondary_teams": list(decision.secondary_teams),
        "auto_response_policy": decision.auto_response_policy,
        "auto_response_template_id": decision.auto_response_template_id,
        "human_review_required": bool(decision.human_review_required),
        "risk_flags": list(decision.risk_flags),
        "reason_codes": list(decision.reason_codes),
        "model_eligibility": decision.model_eligibility,
        "model_called": False,
        "model_bypass_reason": decision.model_bypass_reason,
        "decision_basis": decision.decision_basis,
        "market_framework_status": message.market_framework_status or "established",
        "market_overlay_codes": list(message.market_overlay_codes),
        "market_applicability_note": market_applicability_note,
        "related_message_ids": list(message.linkage.related_message_ids),
        "first_contact_message_id": message.linkage.first_contact_message_id,
        "previous_contact_count": message.linkage.previous_contact_count,
        "attachment_received": message.eligibility.attachment_received,
        "attachment_referenced": message.eligibility.attachment_referenced,
        "identity_document_referenced": message.eligibility.identity_document_referenced,
        "sensitive_data_types": list(_signal_sensitive_types(message)),
        "required_context": [],
        "missing_context": [],
        "decision_limited_by_missing_context": False,
        "policy_basis_ids": list(decision.policy_basis_ids),
        "short_rationale": short_rationale,
    }


def _signal_sensitive_types(message: IngestedMessage) -> tuple[str, ...]:
    mapping = {
        "AUTH_SECRET": "authentication_secret",
        "CVV": "cvv",
        "PAN": "payment_card_number",
        "EMAIL": "email",
        "PHONE": "phone",
        "PLAYER_ID": "player_id",
        "TRANSACTION_REF": "transaction_reference",
        "CURRENCY_AMOUNT": "currency_amount",
        "IDENTITY_DOC_NUMBER": "identity_document_number",
    }
    found = {
        mapping[d.detector_id]
        for d in message.detections
        if d.is_detected() and d.detector_id in mapping
    }
    return tuple(sorted(found))


def manual_fallback_decision(
    message: IngestedMessage,
    *,
    reason: str,
    short_rationale: str,
    market_applicability_note: str | None,
) -> dict[str, Any]:
    """Build a schema-valid provisional fallback when no safe classification exists."""

    const = load_routing_map().constants
    return {
        "message_id": message.msg_id,
        "received_utc": message.received_utc.isoformat().replace("+00:00", "Z"),
        "channel": message.channel,
        "market": message.market,
        "language": message.language,
        "processing_status": "provisional_fallback",
        "category": const.general_category,
        "intent": const.unclassified_intent,
        "secondary_intents": [],
        "priority": "medium",
        "route": const.human,
        "assigned_team": const.general_support_team,
        "secondary_teams": [],
        "auto_response_policy": const.acknowledgment_only,
        "auto_response_template_id": None,
        "human_review_required": True,
        "risk_flags": ["classification_uncertain"],
        "reason_codes": [reason],
        "model_eligibility": "eligible",
        "model_called": False,
        "model_bypass_reason": None,
        "decision_basis": "manual_fallback",
        "market_framework_status": message.market_framework_status or "established",
        "market_overlay_codes": list(message.market_overlay_codes),
        "market_applicability_note": market_applicability_note,
        "related_message_ids": list(message.linkage.related_message_ids),
        "first_contact_message_id": message.linkage.first_contact_message_id,
        "previous_contact_count": message.linkage.previous_contact_count,
        "attachment_received": message.eligibility.attachment_received,
        "attachment_referenced": message.eligibility.attachment_referenced,
        "identity_document_referenced": message.eligibility.identity_document_referenced,
        "sensitive_data_types": list(_signal_sensitive_types(message)),
        "required_context": [],
        "missing_context": [],
        "decision_limited_by_missing_context": True,
        "policy_basis_ids": [],
        "short_rationale": short_rationale,
    }
