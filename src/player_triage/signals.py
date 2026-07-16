"""Derive the deterministic signal context consumed by the Phase 03 engine.

The rule engine and the baseline classifier both operate on a small, typed
:class:`SignalContext` rather than on the raw :class:`IngestedMessage`. This
keeps every downstream stage independent of Phase 02 internals and makes the
inputs to a rule match explicit and testable.

Only sanitized, ingestion-derived material reaches this layer:

* ``text`` is the *redacted* combined subject/body produced in Phase 02. It
  still contains ordinary words (``withdrawal``, ``self-exclude``) but every
  sensitive value has already been replaced by a placeholder, so no PAN/CVV,
  identity number, OTP or player identifier can appear here.
* ``flags`` are booleans derived from detector output and linkage only.

No player_id, subject/body text or matched sensitive value is ever stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Mapping

from .records import IngestedMessage
from .routing import load_routing_map


# Detector-id → the controlled ``sensitive_data_types`` value it represents.
_DETECTOR_SENSITIVE_TYPE: Final[Mapping[str, str]] = {
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

# Application-level context detector (not a policy pattern): does the message
# discuss a payment card at all? Used only to qualify the deterministic PCI
# rule's ``pan_detected AND card_context_detected`` branch.
_CARD_CONTEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:card|visa|mastercard|amex|debit|credit|payment)\b"
)

# Heuristics used to answer the baseline refinement guard questions. These are
# deliberately conservative application heuristics, not classification policy;
# they only qualify *whether a documented refinement applies*, never invent a
# label.
_BONUS_CONTEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:bonus|free spins?|wager(?:ing)?|promo(?:tion)?|cashback|loyalty)\b"
)
_ACCOUNT_SPECIFIC_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:my (?:withdrawal|deposit|balance|payout|account)|pending|stuck|"
    r"declined|not received|not credited|missing|on hold|held|reversed|"
    r"charged twice|duplicate)\b"
)
_CLAIMED_MISSING_WIN_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:missing win|should have won|did ?n['’]?t get paid|"
    r"not paid out|balance does not include the win|win .{0,20}not credited)\b"
)
_PASSPORT_RE: Final[re.Pattern[str]] = re.compile(r"(?i)\bpassport\b")


@dataclass(frozen=True, slots=True)
class SignalContext:
    """Everything a deterministic rule or baseline rule may inspect."""

    msg_id: str
    text: str
    flags: Mapping[str, bool]
    sensitive_data_types: tuple[str, ...]
    previous_contact_count: int
    first_contact_message_id: str | None
    related_message_ids: tuple[str, ...]
    attachment_received: bool
    attachment_referenced: bool
    identity_document_referenced: bool
    market: str
    market_overlay_codes: tuple[str, ...]
    market_framework_status: str
    ingestion_eligibility_state: str
    ingestion_eligibility_reason: str | None

    def flag(self, name: str) -> bool:
        return self.flags.get(name, False)


def _detected_ids(message: IngestedMessage) -> frozenset[str]:
    return frozenset(d.detector_id for d in message.detections if d.is_detected())


def build_signals(message: IngestedMessage) -> SignalContext:
    """Project an :class:`IngestedMessage` into a :class:`SignalContext`."""

    text = message.redacted_text
    detected = _detected_ids(message)

    sensitive_types = tuple(
        sorted(
            {
                _DETECTOR_SENSITIVE_TYPE[d]
                for d in detected
                if d in _DETECTOR_SENSITIVE_TYPE
            }
        )
    )

    repeat_contact = message.linkage.previous_contact_count >= 1
    const = load_routing_map().constants

    flags: dict[str, bool] = {
        # Deterministic safety-rule flags.
        "cvv_detected": "CVV" in detected,
        "auth_secret_detected": "AUTH_SECRET" in detected,
        "pan_detected": "PAN" in detected,
        "card_context_detected": bool(_CARD_CONTEXT_RE.search(text)),
        "prompt_injection_detected": "PROMPT_INJECTION" in detected,
        "identity_document_number_detected": "IDENTITY_DOC_NUMBER" in detected,
        # Linkage / complaint flags.
        "repeat_contact": repeat_contact,
        # Baseline-refinement guard heuristics.
        "contains_bonus_context": bool(_BONUS_CONTEXT_RE.search(text)),
        "account_specific": bool(_ACCOUNT_SPECIFIC_RE.search(text)),
        const.claimed_missing_win_flag: bool(_CLAIMED_MISSING_WIN_RE.search(text)),
        # An explicit expected-vs-received amount is anchored on a detected
        # currency amount (the deterministic amount signal): a dispute cites a
        # concrete figure, a general calculation query does not.
        "explicit_expected_vs_received_amount": "CURRENCY_AMOUNT" in detected,
        # Reference detectors (surface as risk flags; do not alter routing).
        "passport_referenced": bool(_PASSPORT_RE.search(text))
        and message.eligibility.identity_document_referenced,
    }

    return SignalContext(
        msg_id=message.msg_id,
        text=text,
        flags=flags,
        sensitive_data_types=sensitive_types,
        previous_contact_count=message.linkage.previous_contact_count,
        first_contact_message_id=message.linkage.first_contact_message_id,
        related_message_ids=message.linkage.related_message_ids,
        attachment_received=message.eligibility.attachment_received,
        attachment_referenced=message.eligibility.attachment_referenced,
        identity_document_referenced=message.eligibility.identity_document_referenced,
        market=message.market,
        market_overlay_codes=message.market_overlay_codes,
        market_framework_status=message.market_framework_status,
        ingestion_eligibility_state=message.eligibility.state,
        ingestion_eligibility_reason=message.eligibility.reason,
    )
