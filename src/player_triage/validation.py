"""Authoritative semantic cross-field validator.

JSON Schema (``output_schema.json``) enforces field shapes and the structural
``allOf`` invariants. This module is the *second*, semantic validator required
by ``policy/semantic_constraints.json``: it re-checks the safety-critical
cross-field rules independently and additionally scans the finished decision
for any raw sensitive value or player-message quotation.

``validate`` returns a list of :class:`Violation`; an empty list means the
decision is semantically sound. The engine treats any violation as a
fail-closed condition and routes to a manual fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Mapping

from .config import AppConfig
from .routing import RoutingConstants, load_routing_map
from .signals import SignalContext

# Patterns that must never appear in a finished decision.
_PAN_LIKE_RE: Final[re.Pattern[str]] = re.compile(r"(?:\d[ -]?){13,19}")
_PLAYER_ID_RE: Final[re.Pattern[str]] = re.compile(r"\bP-\d{5}\b")
_KNOWN_FIXTURES: Final[tuple[str, ...]] = (
    "4539 1488 0343 6467",
    "4539148803436467",
    "CVV 441",
    "cvv 441",
)

_STRING_FIELDS_TO_SCAN: Final[tuple[str, ...]] = (
    "short_rationale",
    "market_applicability_note",
)


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class SemanticValidator:
    vocab: Mapping[str, frozenset[str]]
    const: RoutingConstants

    @classmethod
    def from_config(cls, config: AppConfig) -> "SemanticValidator":
        catalogues = config.vocab.catalogues()
        vocab = {name: frozenset(values) for name, values in catalogues.items()}
        return cls(vocab=vocab, const=load_routing_map().constants)

    def _known(self, catalogue: str, value: str | None) -> bool:
        if value is None:
            return True
        return value in self.vocab.get(catalogue, frozenset())

    def validate(
        self,
        decision: Mapping[str, Any],
        ctx: SignalContext,
        *,
        model_mode: str = "rules_only",
    ) -> list[Violation]:
        violations: list[Violation] = []
        route = decision.get("route")
        priority = decision.get("priority")
        template = decision.get("auto_response_template_id")
        human_review = decision.get("human_review_required")
        eligibility = decision.get("model_eligibility")
        bypass_reason = decision.get("model_bypass_reason")
        risk_flags = set(decision.get("risk_flags", []))

        # 1) auto_respond without a template.
        if route == self.const.auto_respond and not template:
            violations.append(Violation("AUTO_RESPOND_WITHOUT_TEMPLATE", "auto_respond requires a template"))
        # 2) auto_respond with human review.
        if route == self.const.auto_respond and human_review:
            violations.append(Violation("AUTO_RESPOND_WITH_HUMAN_REVIEW", "auto_respond forbids human review"))
        # 3) auto_respond for non-low priority.
        if route == self.const.auto_respond and priority != "low":
            violations.append(Violation("AUTO_RESPOND_NON_LOW_PRIORITY", "auto_respond requires low priority"))
        # 4) critical without specialist routing / human review.
        if priority == "critical" and (route != "specialist" or not human_review):
            violations.append(Violation("CRITICAL_WITHOUT_SPECIALIST", "critical must be specialist + human review"))
        # 5) a model call is valid only in explicitly enabled local-model mode
        # and only for a final eligible decision.
        if decision.get("model_called") is True and model_mode != "local_model":
            violations.append(Violation("MODEL_CALLED_IN_RULES_ONLY", "model_called must be false"))
        if decision.get("model_called") is True and eligibility != self.const.eligible:
            violations.append(
                Violation("MODEL_CALLED_WHILE_BYPASSED", "model call requires eligible state")
            )
        # 6) bypass eligibility without a bypass reason.
        if isinstance(eligibility, str) and eligibility.startswith("bypass_") and not bypass_reason:
            violations.append(Violation("BYPASS_WITHOUT_REASON", "bypass eligibility requires a reason"))
        # 7) eligible state with a bypass reason.
        if eligibility in ("eligible", "eligible_text_only") and bypass_reason is not None:
            violations.append(Violation("ELIGIBLE_WITH_BYPASS_REASON", "eligible state forbids a bypass reason"))
        # 8) prompt-injection bypass without the flag.
        if eligibility == "bypass_untrusted_input" and "prompt_injection_detected" not in risk_flags:
            violations.append(
                Violation("INJECTION_BYPASS_WITHOUT_FLAG", "injection bypass requires prompt_injection_detected")
            )
        # 9) prohibited-market auto-response.
        if decision.get("market_framework_status") == "prohibited_market" and route == self.const.auto_respond:
            violations.append(Violation("PROHIBITED_MARKET_AUTO_RESPONSE", "prohibited market cannot auto-respond"))
        if decision.get(
            "market_framework_status"
        ) == self.const.prohibited_market_status and self.const.market_compliance_team not in set(
            decision.get("secondary_teams", [])
        ):
            violations.append(
                Violation("PROHIBITED_MARKET_WITHOUT_COMPLIANCE", "prohibited market requires compliance team")
            )
        # 11) account-specific investigation marked safe for static auto-response.
        # A deterministic policy rule (decision_basis == "deterministic") may
        # authorise an auto-response — e.g. an explicit marketing-only opt-out —
        # so this guard only applies to the baseline static-template shortcut.
        if (
            route == self.const.auto_respond
            and ctx.flag("account_specific")
            and decision.get("decision_basis") != "deterministic"
        ):
            violations.append(
                Violation("ACCOUNT_SPECIFIC_AUTO_RESPONSE", "account-specific issue cannot static auto-respond")
            )

        # 10) unknown controlled-vocabulary values.
        violations.extend(self._vocab_violations(decision))

        # 12) raw sensitive values / player-message quotation.
        violations.extend(self._sensitive_scan(decision))

        return violations

    def _vocab_violations(self, decision: Mapping[str, Any]) -> list[Violation]:
        checks_scalar: tuple[tuple[str, str], ...] = (
            ("category", "categories"),
            ("intent", "intents"),
            ("priority", "priorities"),
            ("route", "routes"),
            ("assigned_team", "teams"),
            ("auto_response_policy", "auto_response_policies"),
            ("auto_response_template_id", "auto_response_template_ids"),
            ("model_eligibility", "model_eligibility"),
            ("model_bypass_reason", "model_bypass_reasons"),
            ("decision_basis", "decision_basis"),
            ("market_framework_status", "market_framework_status"),
            ("processing_status", "processing_statuses"),
        )
        violations: list[Violation] = []
        for field_name, catalogue in checks_scalar:
            value = decision.get(field_name)
            if isinstance(value, str) and not self._known(catalogue, value):
                violations.append(Violation("UNKNOWN_VOCAB_VALUE", f"{field_name}={value!r} not in {catalogue}"))

        checks_list: tuple[tuple[str, str], ...] = (
            ("secondary_intents", "intents"),
            ("secondary_teams", "teams"),
            ("risk_flags", "risk_flags"),
            ("reason_codes", "reason_codes"),
            ("market_overlay_codes", "market_overlay_codes"),
            ("sensitive_data_types", "sensitive_data_types"),
            ("required_context", "required_context_keys"),
            ("missing_context", "required_context_keys"),
        )
        for field_name, catalogue in checks_list:
            for value in decision.get(field_name, []):
                if not self._known(catalogue, value):
                    violations.append(
                        Violation("UNKNOWN_VOCAB_VALUE", f"{field_name} entry {value!r} not in {catalogue}")
                    )
        return violations

    def _sensitive_scan(self, decision: Mapping[str, Any]) -> list[Violation]:
        violations: list[Violation] = []
        for field_name in _STRING_FIELDS_TO_SCAN:
            value = decision.get(field_name)
            if not isinstance(value, str):
                continue
            if _PAN_LIKE_RE.search(value):
                violations.append(Violation("RAW_SENSITIVE_VALUE", f"{field_name} contains a long digit run"))
            if _PLAYER_ID_RE.search(value):
                violations.append(Violation("RAW_SENSITIVE_VALUE", f"{field_name} contains a player id"))
            for fixture in _KNOWN_FIXTURES:
                if fixture in value:
                    violations.append(Violation("RAW_SENSITIVE_VALUE", f"{field_name} contains a known fixture value"))
        return violations
