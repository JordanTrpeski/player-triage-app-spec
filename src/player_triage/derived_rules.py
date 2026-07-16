"""Generic, data-driven deterministic-refinement engine (Phase 03B / 03C).

Interprets the authoritative ``policy/derived_refinement_rules.json`` policy
component (loaded and hash-verified by :mod:`player_triage.config`) and applies
its rules to the :class:`~player_triage.working.WorkingDecision` after the
baseline and post-semantic stages. The eight business policies are NOT encoded
in Python — this module is a generic interpreter only. Every rule is generic: it
matches on intent membership, compiled regexes over the redacted combined text,
detector/linkage flags and structured linkage predicates — never on a message id
or a raw-body equality.

Rules never fire when a pre-model safety terminal already decided the message
(``safety_terminal_fired``), so self-harm / PCI / self-exclusion outcomes are
never altered. Effects are applied with ``force`` so a rule can specialise the
result of a non-safety post-semantic rule (e.g. escalate a formal complaint to a
repeated-withdrawal escalation); the safety guard keeps this bounded.

An empty rule set (see :meth:`DerivedRuleEngine.empty`) reproduces the pre-03B
behaviour, which is what a rollback to a policy version without this component
restores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .signals import SignalContext
from .working import LIST_FIELDS, SCALAR_FIELDS, WorkingDecision


@dataclass(frozen=True, slots=True)
class _Predicate:
    intent_in: frozenset[str]
    regex_any: tuple[re.Pattern[str], ...]
    regex_all: tuple[re.Pattern[str], ...]
    regex_none: tuple[re.Pattern[str], ...]
    flags_all: tuple[str, ...]
    flags_any: tuple[str, ...]
    flags_none: tuple[str, ...]
    repeat_or_related: bool
    min_previous_contact: int | None

    def matches(self, decision: WorkingDecision, ctx: SignalContext) -> bool:
        if self.intent_in and decision.intent not in self.intent_in:
            return False
        if self.regex_any and not any(p.search(ctx.text) for p in self.regex_any):
            return False
        if self.regex_all and not all(p.search(ctx.text) for p in self.regex_all):
            return False
        if self.regex_none and any(p.search(ctx.text) for p in self.regex_none):
            return False
        if self.flags_all and not all(ctx.flag(f) for f in self.flags_all):
            return False
        if self.flags_any and not any(ctx.flag(f) for f in self.flags_any):
            return False
        if self.flags_none and any(ctx.flag(f) for f in self.flags_none):
            return False
        if self.repeat_or_related and not (
            ctx.flag("repeat_contact") or bool(ctx.related_message_ids)
        ):
            return False
        if self.min_previous_contact is not None and (
            ctx.previous_contact_count < self.min_previous_contact
        ):
            return False
        return True


@dataclass(frozen=True, slots=True)
class DerivedRule:
    rule_id: str
    predicate: _Predicate
    set_effects: Mapping[str, object]
    minimum_priority: str | None
    add_effects: Mapping[str, tuple[str, ...]]
    policy_basis_ids: tuple[str, ...]


class DerivedRuleConfigurationError(Exception):
    """Raised when a derived rule references an unknown field."""


def _compile(patterns: Sequence[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in patterns)


def _build_rule(raw: Mapping[str, Any]) -> DerivedRule:
    when = raw.get("when", {})
    predicate = _Predicate(
        intent_in=frozenset(when.get("intent_in", ())),
        regex_any=_compile(when.get("regex_any", ())),
        regex_all=_compile(when.get("regex_all", ())),
        regex_none=_compile(when.get("regex_none", ())),
        flags_all=tuple(when.get("flags_all", ())),
        flags_any=tuple(when.get("flags_any", ())),
        flags_none=tuple(when.get("flags_none", ())),
        repeat_or_related=bool(when.get("repeat_or_related", False)),
        min_previous_contact=when.get("min_previous_contact"),
    )
    set_effects = dict(raw.get("set", {}))
    for field_name in set_effects:
        if field_name not in SCALAR_FIELDS:
            raise DerivedRuleConfigurationError(
                f"rule {raw['id']}: set references unknown field {field_name!r}"
            )
    add_effects: dict[str, tuple[str, ...]] = {}
    for field_name, values in raw.get("add", {}).items():
        if field_name not in LIST_FIELDS:
            raise DerivedRuleConfigurationError(
                f"rule {raw['id']}: add references unknown field {field_name!r}"
            )
        add_effects[field_name] = tuple(values)
    return DerivedRule(
        rule_id=raw["id"],
        predicate=predicate,
        set_effects=set_effects,
        minimum_priority=raw.get("minimum_priority"),
        add_effects=add_effects,
        policy_basis_ids=tuple(raw.get("policy_basis_ids", ())),
    )


@dataclass(frozen=True, slots=True)
class DerivedRuleEngine:
    rules: tuple[DerivedRule, ...]
    version: str

    @classmethod
    def from_component(cls, component: Mapping[str, Any]) -> "DerivedRuleEngine":
        version = str(component.get("version", "unknown"))
        return cls(
            rules=tuple(_build_rule(r) for r in component.get("rules", [])),
            version=version,
        )

    @classmethod
    def empty(cls) -> "DerivedRuleEngine":
        """A rule-free engine: reproduces pre-03B behaviour (rollback target)."""

        return cls(rules=(), version="absent")

    def apply(self, decision: WorkingDecision, ctx: SignalContext) -> list[str]:
        """Apply every matching derived rule in order; return matched IDs."""

        if decision.safety_terminal_fired:
            return []
        matched: list[str] = []
        for rule in self.rules:
            if not rule.predicate.matches(decision, ctx):
                continue
            matched.append(rule.rule_id)
            for field_name, value in rule.set_effects.items():
                decision.set_scalar(
                    field_name, value, stage="derived_refinement", rule_id=rule.rule_id, force=True
                )
            if rule.minimum_priority is not None:
                decision.raise_minimum(
                    rule.minimum_priority, stage="derived_refinement", rule_id=rule.rule_id
                )
            for field_name, values in rule.add_effects.items():
                decision.add_values(
                    field_name, list(values), stage="derived_refinement", rule_id=rule.rule_id
                )
            decision.add_policy_basis(list(rule.policy_basis_ids))
        return matched
