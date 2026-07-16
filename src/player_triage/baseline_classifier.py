"""Rules-only baseline semantic classifier.

Scores the intent rules in ``policy/baseline_intent_rules.json`` against the
redacted message text and applies the documented
``post_classification_refinements``. The classifier is deterministic:

* every rule whose patterns match (``all`` or ``any`` mode) contributes its
  fixed score;
* the winning candidate is the highest score, tie-broken by the rule's order
  in the policy file (stable, no randomness);
* only intents/labels defined in the policy are ever produced.

The classifier never assigns priority/route/team on its own beyond what a
documented refinement sets; final routing is the responsibility of
:mod:`player_triage.final_policy`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Sequence

from .errors import ConfigurationError
from .signals import SignalContext
from .working import LIST_FIELDS, SCALAR_FIELDS

# Refinement ``set`` fields that describe routing (as opposed to the intent
# label). Captured so the same treatment can be applied when a message reaches
# the refined intent directly through a baseline rule.
_ROUTING_FIELDS: Final[frozenset[str]] = SCALAR_FIELDS | {"minimum_priority"}


class BaselineConfigurationError(ConfigurationError):
    """Raised when a baseline rule or refinement is malformed."""


@dataclass(frozen=True, slots=True)
class ScoredIntent:
    rule_id: str
    intent: str
    category: str
    score: int
    order: int


@dataclass(slots=True)
class BaselineOutcome:
    category: str | None = None
    intent: str | None = None
    top_intent: str | None = None
    routing_set: dict[str, object] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    secondary_teams: list[str] = field(default_factory=list)
    secondary_intents: list[str] = field(default_factory=list)
    matched_rule_ids: list[str] = field(default_factory=list)
    refinement_ids: list[str] = field(default_factory=list)
    scored: list[ScoredIntent] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _BaselineRule:
    rule_id: str
    category: str
    intent: str
    score: int
    match_mode: str
    patterns: tuple[re.Pattern[str], ...]
    order: int


@dataclass(frozen=True, slots=True)
class _Refinement:
    rule_id: str
    when: Mapping[str, Any]
    set_effects: Mapping[str, object]
    add_effects: Mapping[str, tuple[str, ...]]


def _compile(patterns: Sequence[str], *, rule_id: str) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for index, pattern in enumerate(patterns):
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise BaselineConfigurationError(
                component="baseline_intent_rules",
                message=f"rule {rule_id}: pattern[{index}] does not compile: {exc}",
            ) from exc
    return tuple(compiled)


@dataclass(frozen=True, slots=True)
class BaselineClassifier:
    rules: tuple[_BaselineRule, ...]
    refinements: tuple[_Refinement, ...]

    @classmethod
    def from_policy(cls, policy: Mapping[str, Any]) -> "BaselineClassifier":
        rules: list[_BaselineRule] = []
        for order, raw in enumerate(policy.get("rules", [])):
            if not raw.get("enabled", True):
                continue
            mode = raw["match_mode"]
            if mode not in {"all", "any"}:
                raise BaselineConfigurationError(
                    component="baseline_intent_rules",
                    message=f"rule {raw['id']}: unknown match_mode {mode!r}",
                )
            rules.append(
                _BaselineRule(
                    rule_id=raw["id"],
                    category=raw["category"],
                    intent=raw["intent"],
                    score=int(raw["score"]),
                    match_mode=mode,
                    patterns=_compile(raw.get("patterns", ()), rule_id=raw["id"]),
                    order=order,
                )
            )
        refinements: list[_Refinement] = []
        for raw in policy.get("post_classification_refinements", []):
            add_raw = raw.get("add", {})
            for field_name in add_raw:
                if field_name not in LIST_FIELDS:
                    raise BaselineConfigurationError(
                        component="baseline_intent_rules",
                        message=f"refinement {raw['id']}: add references unknown field {field_name!r}",
                    )
            refinements.append(
                _Refinement(
                    rule_id=raw["id"],
                    when=dict(raw.get("when", {})),
                    set_effects=dict(raw.get("set", {})),
                    add_effects={k: tuple(v) for k, v in add_raw.items()},
                )
            )
        return cls(rules=tuple(rules), refinements=tuple(refinements))

    def _match(self, rule: _BaselineRule, ctx: SignalContext) -> bool:
        if not rule.patterns:
            return False
        if rule.match_mode == "all":
            return all(p.search(ctx.text) for p in rule.patterns)
        return any(p.search(ctx.text) for p in rule.patterns)

    def _when_satisfied(
        self, refinement: _Refinement, ctx: SignalContext, current_intent: str
    ) -> bool:
        for key, expected in refinement.when.items():
            if key == "intent":
                if current_intent != expected:
                    return False
            elif key == "previous_contact_count_gte":
                if ctx.previous_contact_count < int(expected):
                    return False
            else:
                # Every remaining key is a boolean signal flag.
                if ctx.flag(key) != bool(expected):
                    return False
        return True

    def classify(self, ctx: SignalContext) -> BaselineOutcome:
        outcome = BaselineOutcome()
        scored = [
            ScoredIntent(
                rule_id=rule.rule_id,
                intent=rule.intent,
                category=rule.category,
                score=rule.score,
                order=rule.order,
            )
            for rule in self.rules
            if self._match(rule, ctx)
        ]
        outcome.scored = scored
        if not scored:
            return outcome

        # Highest score wins; deterministic tie-break by policy-file order.
        winner = min(scored, key=lambda s: (-s.score, s.order))
        outcome.category = winner.category
        outcome.intent = winner.intent
        outcome.top_intent = winner.intent
        outcome.matched_rule_ids = [s.rule_id for s in scored]

        # Apply refinements in declared order against the evolving intent.
        for refinement in self.refinements:
            if outcome.intent is None:
                break
            if not self._when_satisfied(refinement, ctx, outcome.intent):
                continue
            outcome.refinement_ids.append(refinement.rule_id)
            for field_name, value in refinement.set_effects.items():
                if field_name == "intent":
                    outcome.intent = str(value)
                elif field_name == "category":
                    outcome.category = str(value)
                elif field_name in _ROUTING_FIELDS:
                    outcome.routing_set[field_name] = value
            for field_name, values in refinement.add_effects.items():
                target = getattr(outcome, field_name)
                for entry in values:
                    if entry not in target:
                        target.append(entry)
        return outcome
