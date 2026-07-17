"""Mutable working decision threaded through the Phase 03 stages.

Every material field records *which stage last wrote it* so the final decision
retains enough provenance to explain itself (Phase 03 requirement 3). The
provenance lives in :class:`WorkingDecision.trace`; it is deliberately kept out
of the schema-validated output object (``output_schema.json`` forbids extra
fields) and is surfaced to the CLI and tests through :class:`DecisionTrace`.

Scalar fields are ``None`` until a stage sets them. ``add`` fields accumulate
deduplicated values in first-seen order for stable output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

Stage = Literal[
    "pre_model_safety",
    "baseline_semantic",
    "model_semantic",
    "aggregation",
    "derived_refinement",
    "final_policy",
    "market_overlay",
    "rationale",
    "manual_fallback",
]

PRIORITY_ORDER: Final[dict[str, int]] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

# Scalar fields that a rule ``effects.set`` block may assign. ``minimum_priority``
# is a floor rather than an absolute; it is tracked separately.
SCALAR_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "category",
        "intent",
        "priority",
        "route",
        "assigned_team",
        "auto_response_policy",
        "auto_response_template_id",
        "human_review_required",
        "model_eligibility",
        "model_bypass_reason",
    }
)

# ``effects.add`` list fields.
LIST_FIELDS: Final[frozenset[str]] = frozenset(
    {"risk_flags", "reason_codes", "secondary_intents", "secondary_teams"}
)


def max_priority(a: str | None, b: str | None) -> str | None:
    """Return the higher of two priorities, ignoring ``None``."""

    if a is None:
        return b
    if b is None:
        return a
    return a if PRIORITY_ORDER[a] >= PRIORITY_ORDER[b] else b


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """One provenance record: a stage (optionally a rule) touched fields."""

    stage: Stage
    rule_id: str | None
    fields: tuple[str, ...]
    detail: str = ""


@dataclass(slots=True)
class WorkingDecision:
    """Accumulator mutated across the pipeline stages."""

    msg_id: str

    category: str | None = None
    intent: str | None = None
    priority: str | None = None
    route: str | None = None
    assigned_team: str | None = None
    auto_response_policy: str | None = None
    auto_response_template_id: str | None = None
    human_review_required: bool | None = None
    model_eligibility: str | None = None
    model_bypass_reason: str | None = None

    minimum_priority: str | None = None

    secondary_intents: list[str] = field(default_factory=list)
    secondary_teams: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    policy_basis_ids: list[str] = field(default_factory=list)

    locked_fields: set[str] = field(default_factory=set)
    terminal_rule_fired: bool = False
    safety_terminal_fired: bool = False
    decision_basis: str = "rules_only_baseline"
    trace: list[TraceEntry] = field(default_factory=list)

    # -- scalar handling ----------------------------------------------------
    def set_scalar(
        self,
        field_name: str,
        value: object,
        *,
        stage: Stage,
        rule_id: str | None = None,
        lock: bool = False,
        force: bool = False,
    ) -> bool:
        """Set a scalar field unless it is locked. Returns True if written."""

        if field_name in self.locked_fields and not force:
            return False
        setattr(self, field_name, value)
        if lock:
            self.locked_fields.add(field_name)
        self.trace.append(TraceEntry(stage=stage, rule_id=rule_id, fields=(field_name,)))
        return True

    def raise_minimum(self, priority: str, *, stage: Stage, rule_id: str | None = None) -> None:
        self.minimum_priority = max_priority(self.minimum_priority, priority)
        self.trace.append(
            TraceEntry(stage=stage, rule_id=rule_id, fields=("minimum_priority",))
        )

    # -- list handling ------------------------------------------------------
    def add_values(
        self,
        field_name: str,
        values: list[str],
        *,
        stage: Stage,
        rule_id: str | None = None,
    ) -> None:
        target: list[str] = getattr(self, field_name)
        added: list[str] = []
        for value in values:
            if value not in target:
                target.append(value)
                added.append(value)
        if added:
            self.trace.append(
                TraceEntry(stage=stage, rule_id=rule_id, fields=tuple(added), detail=field_name)
            )

    def add_policy_basis(self, ids: list[str]) -> None:
        for value in ids:
            if value not in self.policy_basis_ids:
                self.policy_basis_ids.append(value)
