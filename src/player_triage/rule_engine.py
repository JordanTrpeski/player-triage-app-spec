"""Generic evaluator for the Rule DSL 3.0 defined in ``policy/rule_dsl.md``.

The evaluator is data-driven: it compiles the ``match`` tree and ``effects`` of
every rule in ``policy/policy_rules.json`` and applies them to a
:class:`~player_triage.working.WorkingDecision`. No message ID and no rule
identity is hard-coded here — behaviour comes entirely from the policy file.

Supported ``match`` nodes (recursive):

* ``{"any": [...]}`` / ``{"all": [...]}``
* ``{"field": <name>, "regex_any": [...]}`` — any pattern matches the field
* ``{"field": <name>, "regex_none": [...]}`` — no pattern matches the field
* ``{"flag": <name>, "equals": <bool>}`` — a derived boolean signal

Terminal precedence follows the DSL: the first terminal rule that fires locks
the scalar fields it sets so later classification cannot override them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Final, Mapping, Sequence

from .errors import ConfigurationError
from .signals import SignalContext
from .working import LIST_FIELDS, SCALAR_FIELDS, Stage, WorkingDecision

Matcher = Callable[[SignalContext], bool]

_KNOWN_FIELDS: Final[frozenset[str]] = frozenset({"combined_text"})


class RuleConfigurationError(ConfigurationError):
    """Raised when a policy rule cannot be compiled."""


@dataclass(frozen=True, slots=True)
class CompiledRule:
    rule_id: str
    order: int
    phase: str
    terminal: bool
    matcher: Matcher
    set_effects: Mapping[str, object]
    add_effects: Mapping[str, tuple[str, ...]]
    policy_basis_ids: tuple[str, ...]


def _field_text(ctx: SignalContext, field_name: str) -> str:
    if field_name == "combined_text":
        return ctx.text
    raise RuleConfigurationError(
        component="policy_rules",
        message=f"match references unknown field {field_name!r}",
    )


def _compile_regexes(patterns: Sequence[str], *, rule_id: str) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for index, pattern in enumerate(patterns):
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise RuleConfigurationError(
                component="policy_rules",
                message=f"rule {rule_id}: match pattern[{index}] does not compile: {exc}",
            ) from exc
    return tuple(compiled)


def _compile_match(node: Mapping[str, Any], *, rule_id: str) -> Matcher:
    if "any" in node:
        children = [_compile_match(child, rule_id=rule_id) for child in node["any"]]
        return lambda ctx: any(child(ctx) for child in children)
    if "all" in node:
        children = [_compile_match(child, rule_id=rule_id) for child in node["all"]]
        return lambda ctx: all(child(ctx) for child in children)
    if "flag" in node:
        flag_name = node["flag"]
        expected = bool(node.get("equals", True))
        return lambda ctx: ctx.flag(flag_name) == expected
    if "field" in node:
        field_name = node["field"]
        if "regex_any" in node:
            patterns = _compile_regexes(node["regex_any"], rule_id=rule_id)
            return lambda ctx: any(p.search(_field_text(ctx, field_name)) for p in patterns)
        if "regex_none" in node:
            patterns = _compile_regexes(node["regex_none"], rule_id=rule_id)
            return lambda ctx: not any(
                p.search(_field_text(ctx, field_name)) for p in patterns
            )
    raise RuleConfigurationError(
        component="policy_rules",
        message=f"rule {rule_id}: unsupported match node keys {sorted(node)}",
    )


def _compile_rule(raw: Mapping[str, Any]) -> CompiledRule:
    rule_id = raw["id"]
    effects = raw.get("effects", {})
    set_effects: Mapping[str, object] = dict(effects.get("set", {}))
    for field_name in set_effects:
        if field_name not in SCALAR_FIELDS and field_name != "minimum_priority":
            raise RuleConfigurationError(
                component="policy_rules",
                message=f"rule {rule_id}: effects.set references unknown field {field_name!r}",
            )
    add_effects_raw = effects.get("add", {})
    add_effects: dict[str, tuple[str, ...]] = {}
    for field_name, values in add_effects_raw.items():
        if field_name not in LIST_FIELDS:
            raise RuleConfigurationError(
                component="policy_rules",
                message=f"rule {rule_id}: effects.add references unknown field {field_name!r}",
            )
        add_effects[field_name] = tuple(values)
    return CompiledRule(
        rule_id=rule_id,
        order=int(raw["order"]),
        phase=raw["phase"],
        terminal=bool(raw["terminal"]),
        matcher=_compile_match(raw["match"], rule_id=rule_id),
        set_effects=set_effects,
        add_effects=add_effects,
        policy_basis_ids=tuple(raw.get("policy_basis_ids", ())),
    )


@dataclass(frozen=True, slots=True)
class RuleEngine:
    """Ordered, compiled deterministic rule set."""

    pre_model: tuple[CompiledRule, ...]
    post_semantic: tuple[CompiledRule, ...]

    @classmethod
    def from_policy(cls, policy: Mapping[str, Any]) -> "RuleEngine":
        rules = [
            _compile_rule(raw)
            for raw in policy.get("rules", [])
            if raw.get("enabled", True)
        ]
        rules.sort(key=lambda rule: rule.order)
        pre = tuple(r for r in rules if r.phase == "pre_model")
        post = tuple(r for r in rules if r.phase == "post_semantic")
        unknown_phase = {r.phase for r in rules} - {"pre_model", "post_semantic"}
        if unknown_phase:
            raise RuleConfigurationError(
                component="policy_rules",
                message=f"unknown rule phase(s): {sorted(unknown_phase)}",
            )
        return cls(pre_model=pre, post_semantic=post)

    def _apply(self, rule: CompiledRule, decision: WorkingDecision, stage: Stage) -> None:
        for field_name, value in rule.set_effects.items():
            if field_name == "minimum_priority":
                assert isinstance(value, str)
                decision.raise_minimum(value, stage=stage, rule_id=rule.rule_id)
                continue
            decision.set_scalar(
                field_name,
                value,
                stage=stage,
                rule_id=rule.rule_id,
                lock=rule.terminal,
            )
        for field_name, values in rule.add_effects.items():
            decision.add_values(field_name, list(values), stage=stage, rule_id=rule.rule_id)
        decision.add_policy_basis(list(rule.policy_basis_ids))

    def evaluate_pre_model(
        self, decision: WorkingDecision, ctx: SignalContext
    ) -> list[str]:
        """Evaluate pre-model rules in order; return the IDs that matched.

        All matching pre-model rules contribute their additive effects; the
        first terminal rule that fires locks its scalar effects and marks the
        decision terminal so the semantic stage cannot override those fields.
        """

        matched: list[str] = []
        for rule in self.pre_model:
            if not rule.matcher(ctx):
                continue
            matched.append(rule.rule_id)
            self._apply(rule, decision, "pre_model_safety")
            if rule.terminal:
                decision.safety_terminal_fired = True
                if not decision.terminal_rule_fired:
                    decision.terminal_rule_fired = True
                    decision.decision_basis = "deterministic"
        return matched

    def evaluate_post_semantic(
        self, decision: WorkingDecision, ctx: SignalContext
    ) -> list[str]:
        """Evaluate post-semantic rules.

        Skipped entirely when a terminal pre-model safety rule already fired: a
        safety terminal outranks a complaint/marketing/reopen override.
        """

        if decision.terminal_rule_fired:
            return []
        matched: list[str] = []
        for rule in self.post_semantic:
            if not rule.matcher(ctx):
                continue
            matched.append(rule.rule_id)
            self._apply(rule, decision, "final_policy")
            if rule.terminal and not decision.terminal_rule_fired:
                decision.terminal_rule_fired = True
                decision.decision_basis = "deterministic"
        return matched
