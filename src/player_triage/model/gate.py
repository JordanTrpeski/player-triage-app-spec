"""Deterministic pre-call safety gate for the optional local model."""

from __future__ import annotations

from dataclasses import dataclass, fields

from ..records import IngestedMessage
from ..signals import SignalContext
from ..working import WorkingDecision
from .contract import ModelClassificationRequest


@dataclass(frozen=True, slots=True)
class ModelGateOutcome:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ModelCallGate:
    """Proves every required condition before a request can be constructed."""

    mode: str
    kill_switch: bool = False

    def evaluate(
        self,
        message: IngestedMessage,
        ctx: SignalContext,
        decision: WorkingDecision,
    ) -> ModelGateOutcome:
        if self.mode != "local_model":
            return ModelGateOutcome(False, "MODE_NOT_LOCAL_MODEL")
        if self.kill_switch:
            return ModelGateOutcome(False, "KILL_SWITCH_ACTIVE")
        if message.eligibility.state != "eligible":
            return ModelGateOutcome(False, _ingestion_reason(message.eligibility.state))
        if decision.safety_terminal_fired:
            return ModelGateOutcome(False, "SAFETY_TERMINAL")
        if decision.terminal_rule_fired:
            return ModelGateOutcome(False, "DETERMINISTIC_TERMINAL")
        if decision.model_eligibility not in (None, "eligible"):
            return ModelGateOutcome(False, "DETERMINISTIC_BYPASS")
        if ctx.sensitive_data_types and any(
            value in {"authentication_secret", "cvv", "payment_card_number"}
            for value in ctx.sensitive_data_types
        ):
            return ModelGateOutcome(False, "SENSITIVE_BYPASS")
        if ctx.flag("prompt_injection_detected"):
            return ModelGateOutcome(False, "PROMPT_INJECTION_BYPASS")
        if message.eligibility.attachment_received:
            return ModelGateOutcome(False, "ATTACHMENT_BYPASS")
        if message.eligibility.reason == "redaction_uncertain":
            return ModelGateOutcome(False, "REDACTION_UNCERTAIN")
        if message.eligibility.state == "invalid_input":
            return ModelGateOutcome(False, "INPUT_INVALID")
        if not message.redacted_text.strip():
            return ModelGateOutcome(False, "INPUT_INVALID")
        return ModelGateOutcome(True, "ALLOWED")

    @staticmethod
    def build_request(
        message: IngestedMessage,
        *,
        categories: tuple[str, ...],
        intents: tuple[str, ...],
    ) -> ModelClassificationRequest:
        """Construct the only request shape available to providers.

        The explicit field audit makes an accidental future addition of raw or
        player-identity fields fail closed during development and tests.
        """

        names = {item.name for item in fields(ModelClassificationRequest)}
        forbidden = {"raw_text", "subject", "body", "player_id"}
        if names.intersection(forbidden):
            raise RuntimeError("model request contract contains a forbidden field")
        return ModelClassificationRequest(
            message_id=message.msg_id,
            redacted_text=message.redacted_text,
            language=message.language,
            categories=categories,
            intents=intents,
        )


def _ingestion_reason(state: str) -> str:
    return {
        "bypass_sensitive": "SENSITIVE_BYPASS",
        "bypass_attachment": "ATTACHMENT_BYPASS",
        "bypass_untrusted_input": "PROMPT_INJECTION_BYPASS",
        "redaction_uncertain": "REDACTION_UNCERTAIN",
        "invalid_input": "INPUT_INVALID",
    }.get(state, "INGESTION_NOT_ELIGIBLE")
