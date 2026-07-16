"""Deterministic final-policy application, market overlay and rationale.

This stage turns a resolved (category, intent) plus accumulated rule effects
into the authoritative priority / route / team / auto-response fields, then
applies the market overlay and renders the approved rationale.

Routing is derived, in order of authority, from:

1. scalar fields already fixed by a deterministic rule (never overridden);
2. the routing captured from a baseline *refinement* whose result intent equals
   the final intent (so a directly-classified intent gets the same treatment as
   the refined path);
3. the static-information template table (approved static templates only);
4. conservative, fail-closed defaults (human review, acknowledgment only).

The relational maps (category default owner, static-template intents, intent
reason codes) and structural constants live in ``phase03_routing.json`` and are
loaded through :mod:`player_triage.routing`; template IDs are additionally
validated against ``policy/auto_response_templates.json`` at construction so a
policy change surfaces here rather than drifting silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping

from .errors import ConfigurationError
from .routing import RoutingConstants, RoutingMap, load_routing_map
from .signals import SignalContext
from .working import WorkingDecision, max_priority

# Risk flags that forbid a static auto-response even if the intent looks routine.
_AUTO_RESPONSE_FORBIDDEN_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "self_harm_signal",
        "self_exclusion_explicit",
        "sensitive_authentication_data",
        "full_pan_exposed",
        "cvv_exposed",
        "prompt_injection_detected",
        "underage_reported",
        "active_account_takeover",
        "loss_of_control",
        "harm_linked_closure",
        "unauthorized_card_use",
        "formal_complaint",
        "cool_off_active",
        "redaction_uncertain",
    }
)

# Market applicability note keyed by framework status (overlay presentation text).
# Keys are market_framework_status values (an exempt catalogue); values are free
# text, so no classification-catalogue literal appears here.
_OVERLAY_NOTES: Final[Mapping[str, str | None]] = {
    "established": None,
    "prohibited_market": (
        "Online money games are prohibited; the triage result must not be treated as "
        "approval to facilitate continued gambling or payment activity."
    ),
    "casino_applicability_unconfirmed": (
        "Current GRAI licensing phase covers remote betting; online-casino applicability "
        "is unconfirmed."
    ),
    "transitional": (
        "The market is transitional; future licensed-operator duties are not assumed to "
        "apply to every transitional provider."
    ),
}


class FinalPolicyConfigurationError(ConfigurationError):
    """Raised when the static template table conflicts with the policy catalogue."""


@dataclass(frozen=True, slots=True)
class FinalPolicy:
    template_owner: Mapping[str, str]
    approved_template_ids: frozenset[str]
    not_approved_reasons: frozenset[str]
    routing_profiles: Mapping[str, Mapping[str, object]]
    rationale_templates: Mapping[str, str]
    routing_map: RoutingMap

    @property
    def const(self) -> RoutingConstants:
        return self.routing_map.constants

    @classmethod
    def from_config(
        cls,
        auto_response_templates: Mapping[str, Any],
        baseline_intent_rules: Mapping[str, Any],
        rationale_templates: Mapping[str, Any],
    ) -> "FinalPolicy":
        routing_map = load_routing_map()
        owners: dict[str, str] = {}
        approved: set[str] = set()
        for template in auto_response_templates.get("templates", []):
            owners[template["id"]] = template["owner"]
            approved.add(template["id"])
        not_approved = set(auto_response_templates.get("not_approved", []))

        # Validate the static routing table against the approved catalogue.
        for intent, (template_id, _reason) in routing_map.static_template_intents.items():
            if template_id not in approved or template_id in not_approved:
                raise FinalPolicyConfigurationError(
                    component="auto_response_templates",
                    message=(
                        f"static template routing for intent {intent!r} references "
                        f"template {template_id!r} which is not an approved static template"
                    ),
                )

        routing_profiles = _build_routing_profiles(baseline_intent_rules)
        templates = rationale_templates.get("templates", {})
        if not isinstance(templates, dict):
            raise FinalPolicyConfigurationError(
                component="rationale_templates",
                message="rationale templates block is not an object",
            )
        return cls(
            template_owner=owners,
            approved_template_ids=frozenset(approved),
            not_approved_reasons=frozenset(not_approved),
            routing_profiles=routing_profiles,
            rationale_templates=templates,
            routing_map=routing_map,
        )

    # -- stage d: routing ---------------------------------------------------
    def apply_routing(self, decision: WorkingDecision, ctx: SignalContext) -> None:
        const = self.const
        intent = decision.intent
        # Seed the canonical reason code for the business intent.
        if intent is not None and intent in self.routing_map.intent_reason_code:
            decision.add_values(
                "reason_codes",
                [self.routing_map.intent_reason_code[intent]],
                stage="final_policy",
            )

        # 1) routing captured from a refinement for this exact intent.
        if intent is not None and intent in self.routing_profiles:
            self._apply_profile(decision, self.routing_profiles[intent])

        # 2) static template auto-response (only when clearly safe).
        static = self.routing_map.static_template_intents
        if (
            intent is not None
            and intent in static
            and not decision.terminal_rule_fired
            and self._auto_response_allowed(decision, ctx)
        ):
            template_id, reason_code = static[intent]
            decision.set_scalar("route", const.auto_respond, stage="final_policy")
            decision.set_scalar("priority", "low", stage="final_policy")
            decision.set_scalar("auto_response_policy", const.allowed_template, stage="final_policy")
            decision.set_scalar("auto_response_template_id", template_id, stage="final_policy")
            decision.set_scalar("assigned_team", self.template_owner[template_id], stage="final_policy")
            decision.set_scalar("human_review_required", False, stage="final_policy")
            decision.add_values("reason_codes", [reason_code], stage="final_policy")

        # 3) an intent whose canonical reason maps to a non-approved template
        # (e.g. the tax disclaimer) must route to human with requires_approval.
        intent_reason = (
            self.routing_map.intent_reason_code.get(intent) if intent is not None else None
        )
        if intent_reason is not None and intent_reason in self.not_approved_reasons:
            decision.set_scalar("route", const.human, stage="final_policy")
            decision.set_scalar("priority", "low", stage="final_policy")
            decision.set_scalar("auto_response_policy", const.requires_approval, stage="final_policy")

        # 4) conservative defaults for everything still unset.
        if decision.priority is None:
            decision.set_scalar("priority", "medium", stage="final_policy")
        if decision.route is None:
            decision.set_scalar("route", const.human, stage="final_policy")
        if decision.assigned_team is None and decision.category is not None:
            decision.set_scalar(
                "assigned_team",
                self.routing_map.category_default_team.get(
                    decision.category, const.general_support_team
                ),
                stage="final_policy",
            )
        if decision.auto_response_policy is None:
            policy = (
                const.allowed_template
                if decision.route == const.auto_respond
                else const.acknowledgment_only
            )
            decision.set_scalar("auto_response_policy", policy, stage="final_policy")
        if decision.model_eligibility is None:
            decision.set_scalar("model_eligibility", const.eligible, stage="final_policy")

        # Apply the accumulated minimum-priority floor.
        floored = max_priority(decision.priority, decision.minimum_priority)
        if floored is not None and floored != decision.priority:
            decision.set_scalar("priority", floored, stage="final_policy", force=True)

        self._enforce_scalar_consistency(decision)

    def refine_sensitive_bypass_reason(
        self, decision: WorkingDecision, ctx: SignalContext
    ) -> None:
        """Specialise the PCI bypass reason when both PAN and CVV were detected.

        The ``PCI_SENSITIVE_AUTH_DATA`` rule sets the general
        ``sensitive_payment_or_authentication_data`` reason. When the detectors
        found *both* a full PAN and a CVV, the more specific
        ``pan_and_cvv_detected`` reason is emitted instead. Any other sensitive
        payment/authentication exposure (CVV-only, authentication-secret-only,
        PAN-in-card-context-only) retains the general reason. Both values are
        members of the ``model_bypass_reasons`` catalogue; this is engine logic
        keyed on detector signals, not a policy edit.
        """

        if (
            decision.model_eligibility == "bypass_sensitive"
            and ctx.flag("pan_detected")
            and ctx.flag("cvv_detected")
        ):
            decision.set_scalar(
                "model_bypass_reason",
                "pan_and_cvv_detected",
                stage="final_policy",
                force=True,
            )

    def _apply_profile(self, decision: WorkingDecision, profile: Mapping[str, object]) -> None:
        for field_name, value in profile.items():
            if field_name == "minimum_priority":
                assert isinstance(value, str)
                decision.raise_minimum(value, stage="final_policy")
            elif getattr(decision, field_name) is None:
                decision.set_scalar(field_name, value, stage="final_policy")

    def _auto_response_allowed(self, decision: WorkingDecision, ctx: SignalContext) -> bool:
        const = self.const
        if ctx.flag("account_specific"):
            return False
        if ctx.market_framework_status == const.prohibited_market_status:
            return False
        if decision.model_eligibility not in (None, const.eligible):
            return False
        if any(flag in _AUTO_RESPONSE_FORBIDDEN_FLAGS for flag in decision.risk_flags):
            return False
        return True

    def _enforce_scalar_consistency(self, decision: WorkingDecision) -> None:
        const = self.const
        # Critical implies specialist + human review (schema invariant).
        if decision.priority == "critical":
            decision.set_scalar("route", const.specialist, stage="final_policy", force=True)
            decision.set_scalar("human_review_required", True, stage="final_policy", force=True)
        # Non-auto routes never carry a template and always need human review.
        if decision.route in (const.human, const.specialist):
            decision.set_scalar("auto_response_template_id", None, stage="final_policy", force=True)
            decision.set_scalar("human_review_required", True, stage="final_policy", force=True)
        if decision.human_review_required is None:
            decision.set_scalar(
                "human_review_required",
                decision.route != const.auto_respond,
                stage="final_policy",
            )

    # -- stage e: market overlay -------------------------------------------
    def apply_overlay(self, decision: WorkingDecision, ctx: SignalContext) -> str | None:
        const = self.const
        status = ctx.market_framework_status or "established"
        if status == const.prohibited_market_status:
            decision.add_values(
                "secondary_teams", [const.market_compliance_team], stage="market_overlay"
            )
            decision.add_values(
                "reason_codes", [const.india_overlay_reason], stage="market_overlay"
            )
            if decision.route == const.auto_respond:
                # Prohibited market must not auto-respond: fail closed to human.
                decision.set_scalar("route", const.human, stage="market_overlay", force=True)
                decision.set_scalar(
                    "priority",
                    max_priority(decision.priority, "medium") or "medium",
                    stage="market_overlay",
                    force=True,
                )
                decision.set_scalar(
                    "auto_response_policy", const.acknowledgment_only, stage="market_overlay", force=True
                )
                decision.set_scalar("auto_response_template_id", None, stage="market_overlay", force=True)
                decision.set_scalar("human_review_required", True, stage="market_overlay", force=True)
        return _OVERLAY_NOTES.get(status)

    # -- stage f: rationale -------------------------------------------------
    def render_rationale(self, decision: WorkingDecision) -> str:
        parts: list[str] = []
        for reason_code in decision.reason_codes:
            text = self.rationale_templates.get(reason_code)
            if text:
                parts.append(text)
        rendered = " ".join(parts).strip()
        if not rendered:
            rendered = self.rationale_templates.get(
                "UNCLASSIFIED_MANUAL_REVIEW", "Manual review required."
            )
        if len(rendered) > 240:
            rendered = _truncate_words(rendered, 240)
        return rendered


def _truncate_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    if " " in clipped:
        clipped = clipped[: clipped.rfind(" ")]
    return clipped.rstrip()


def _build_routing_profiles(
    baseline_intent_rules: Mapping[str, Any],
) -> Mapping[str, Mapping[str, object]]:
    """Capture routing scalars from refinement ``set`` blocks, keyed by result intent."""

    routing_fields = {
        "priority",
        "route",
        "assigned_team",
        "auto_response_policy",
        "auto_response_template_id",
        "human_review_required",
        "model_eligibility",
        "model_bypass_reason",
        "minimum_priority",
    }
    profiles: dict[str, dict[str, object]] = {}
    for refinement in baseline_intent_rules.get("post_classification_refinements", []):
        set_block = refinement.get("set", {})
        result_intent = set_block.get("intent") or refinement.get("when", {}).get("intent")
        if not isinstance(result_intent, str):
            continue
        captured = {k: v for k, v in set_block.items() if k in routing_fields}
        if not captured:
            continue
        profiles.setdefault(result_intent, {}).update(captured)
    return profiles
