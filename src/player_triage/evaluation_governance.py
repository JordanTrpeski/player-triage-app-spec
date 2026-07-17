"""Non-compensatory safety, baselines, change impact and activation gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_io import sha256_file
from .config import AppConfig
from .evaluation import evaluate_gates
from .evaluation_datasets import DatasetRun
from .evaluation_metrics import DatasetMetrics, PRIORITY_ORDER, ROUTE_ORDER
from .routing import RoutingMap, load_routing_map

_ROUTING = load_routing_map()

COMPARISON_FIELDS: tuple[str, ...] = (
    "category",
    "intent",
    "secondary_intents",
    "priority",
    "route",
    "assigned_team",
    "secondary_teams",
    "auto_response_policy",
    "auto_response_template_id",
    "human_review_required",
    "model_eligibility",
    "model_bypass_reason",
    "risk_flags",
    "reason_codes",
    "short_rationale",
)


@dataclass(frozen=True, slots=True)
class SafetyGateResult:
    gate_id: str
    passed: bool
    dataset_name: str
    detail_code: str
    locked: bool = True


@dataclass(frozen=True, slots=True)
class RegressionBaseline:
    baseline_version: str
    policy_bundle_version: str
    application_version: str
    dataset_name: str
    dataset_version: str
    dataset_digest: str
    canonical_decision_digest: str
    expected_metrics: Mapping[str, object]
    expected_safety_gates: Mapping[str, bool]
    approved_mismatches: tuple[Mapping[str, object], ...]
    created_at: str
    owner: str
    reviewer: str
    status: str


def evaluate_non_compensatory_gates(
    config: AppConfig,
    runs: Sequence[DatasetRun],
    *,
    artifacts_verified: bool,
    audit_schema_valid: bool = True,
) -> tuple[SafetyGateResult, ...]:
    by_name = {run.dataset.name: run for run in runs}
    supplied = by_name.get("supplied-40")
    output: list[SafetyGateResult] = []
    if supplied is not None:
        for gate in evaluate_gates(config, supplied.results_by_id):
            output.append(
                SafetyGateResult(
                    gate.gate_id,
                    gate.passed,
                    supplied.dataset.name,
                    "ASSERTION_SATISFIED" if gate.passed else "ASSERTION_FAILED",
                )
            )

    all_results = {
        (run.dataset.name, message_id): result
        for run in runs
        for message_id, result in run.results_by_id.items()
    }
    all_decisions = [result.decision for result in all_results.values()]
    explicit_intent = next(
        value for value in config.vocab.intents if "permanent_self_exclusion" in value
    )
    responsible_category = next(
        value for value in config.vocab.categories if "responsible" in value.casefold()
    )

    explicit_expected: list[tuple[str, str]] = []
    harm_expected: list[tuple[str, str]] = []
    secret_expected: list[tuple[str, str]] = []
    injection_expected: list[tuple[str, str]] = []
    for run in runs:
        for message_id, safety in run.dataset.safety_by_id.items():
            key = (run.dataset.name, message_id)
            if safety.get("must_be_explicit_se"):
                explicit_expected.append(key)
            if safety.get("expect_rg_critical") or safety.get("expect_high_risk"):
                harm_expected.append(key)
            if safety.get("secret_case"):
                secret_expected.append(key)
            if safety.get("injection_case"):
                injection_expected.append(key)

    output.extend(
        [
            _all_gate(
                "L01_EXPLICIT_SELF_EXCLUSION_RECALL",
                explicit_expected,
                all_results,
                lambda decision: decision.get("intent") == explicit_intent
                and decision.get("priority") == "critical"
                and decision.get("model_called") is False,
            ),
            _all_gate(
                "L02_HARM_LOSS_OF_CONTROL_ESCALATION",
                harm_expected,
                all_results,
                lambda decision: decision.get("category") == responsible_category
                and decision.get("priority") == "critical",
            ),
            _all_gate(
                "L03_SENSITIVE_SECRET_BYPASS",
                secret_expected,
                all_results,
                lambda decision: decision.get("model_eligibility") == "bypass_sensitive"
                and decision.get("model_called") is False,
            ),
            _all_gate(
                "L04_PROMPT_INJECTION_BYPASS",
                injection_expected,
                all_results,
                lambda decision: decision.get("model_eligibility")
                == "bypass_untrusted_input"
                and decision.get("model_called") is False,
            ),
            SafetyGateResult(
                "L05_CRITICAL_SPECIALIST_INVARIANT",
                all(
                    decision.get("route") == "specialist"
                    for decision in all_decisions
                    if decision.get("priority") == "critical"
                ),
                "all-rules-only",
                "CRITICAL_ROUTE_CHECKED",
            ),
            SafetyGateResult(
                "L06_NO_UNSAFE_AUTO_RESPONSE",
                all(_safe_auto_response(decision, _ROUTING) for decision in all_decisions),
                "all-rules-only",
                "AUTO_RESPONSE_POLICY_CHECKED",
            ),
            SafetyGateResult(
                "L07_ZERO_MODEL_CALLS",
                all(decision.get("model_called") is False for decision in all_decisions),
                "all-rules-only",
                "MODEL_CALL_COUNT_ZERO",
            ),
            SafetyGateResult(
                "L08_NO_AUTONOMOUS_RESTRICTED_ACTIONS",
                all(_contains_no_action_fields(decision) for decision in all_decisions),
                "all-rules-only",
                "NO_ACTION_FIELDS",
            ),
            SafetyGateResult(
                "L09_MARKET_OVERLAY_GUARD",
                all(_safe_market_overlay(decision) for decision in all_decisions),
                "all-rules-only",
                "MARKET_OVERLAY_CHECKED",
            ),
            SafetyGateResult(
                "L10_OUTPUT_AND_AUDIT_SCHEMA_100_PERCENT",
                all(result.schema_valid and not result.semantic_violations for result in all_results.values())
                and audit_schema_valid,
                "all-rules-only",
                "SCHEMA_AND_SEMANTIC_VALID",
            ),
            SafetyGateResult(
                "L11_NO_RAW_SENSITIVE_ARTIFACT_DATA",
                artifacts_verified,
                "supplied-40",
                "ARTIFACT_SAFETY_SCAN_VERIFIED" if artifacts_verified else "ARTIFACT_SCAN_FAILED",
            ),
        ]
    )
    return tuple(output)


def load_baseline(path: Path) -> RegressionBaseline:
    document = json.loads(path.read_text(encoding="utf-8"))
    return RegressionBaseline(
        baseline_version=str(document["baseline_version"]),
        policy_bundle_version=str(document["policy_bundle_version"]),
        application_version=str(document["application_version"]),
        dataset_name=str(document["dataset_name"]),
        dataset_version=str(document["dataset_version"]),
        dataset_digest=str(document["dataset_digest"]),
        canonical_decision_digest=str(document["canonical_decision_digest"]),
        expected_metrics=document["expected_metrics"],
        expected_safety_gates=document["expected_safety_gates"],
        approved_mismatches=tuple(document["approved_mismatches"]),
        created_at=str(document["created_at"]),
        owner=str(document["owner"]),
        reviewer=str(document["reviewer"]),
        status=str(document["status"]),
    )


def compare_baseline(
    baseline: RegressionBaseline,
    metrics: DatasetMetrics,
    canonical_digest: str,
    gates: Sequence[SafetyGateResult],
) -> dict[str, object]:
    current_mismatches = {
        (item.message_id, item.field) for item in metrics.mismatches
    }
    approved = {
        (str(item["message_id"]), str(item["field"]))
        for item in baseline.approved_mismatches
    }
    gate_map = {item.gate_id: item.passed for item in gates}
    gate_changes = {
        key: {"expected": expected, "actual": gate_map.get(key)}
        for key, expected in baseline.expected_safety_gates.items()
        if gate_map.get(key) != expected
    }
    return {
        "baseline_version": baseline.baseline_version,
        "dataset_digest_match": metrics.dataset_digest == baseline.dataset_digest,
        "canonical_digest_match": canonical_digest == baseline.canonical_decision_digest,
        "new_matches": [
            {"message_id": mid, "field": field}
            for mid, field in sorted(approved - current_mismatches)
        ],
        "new_mismatches": [
            {"message_id": mid, "field": field}
            for mid, field in sorted(current_mismatches - approved)
        ],
        "resolved_mismatches": [
            {"message_id": mid, "field": field}
            for mid, field in sorted(approved - current_mismatches)
        ],
        "safety_gate_changes": gate_changes,
        "passed": (
            metrics.dataset_digest == baseline.dataset_digest
            and canonical_digest == baseline.canonical_decision_digest
            and current_mismatches == approved
            and not gate_changes
        ),
    }


def compare_decisions(
    active: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Mapping[str, Any]],
    *,
    active_mismatches: Sequence[tuple[str, str]] = (),
    candidate_mismatches: Sequence[tuple[str, str]] = (),
) -> dict[str, object]:
    changed: list[dict[str, object]] = []
    priority_increases = 0
    priority_decreases = 0
    route_changes = 0
    team_changes = 0
    auto_response_changes = 0
    bypass_changes = 0
    newly_invalid: list[str] = []
    for message_id in sorted(set(active) | set(candidate)):
        left = active.get(message_id)
        right = candidate.get(message_id)
        if left is None or right is None:
            newly_invalid.append(message_id)
            continue
        fields = [field for field in COMPARISON_FIELDS if left.get(field) != right.get(field)]
        if not fields:
            continue
        changed.append({"message_id": message_id, "fields_changed": fields})
        lp = PRIORITY_ORDER.get(str(left.get("priority")), -1)
        rp = PRIORITY_ORDER.get(str(right.get("priority")), -1)
        priority_increases += int(rp > lp)
        priority_decreases += int(rp < lp)
        route_changes += int(left.get("route") != right.get("route"))
        team_changes += int(
            left.get("assigned_team") != right.get("assigned_team")
            or left.get("secondary_teams") != right.get("secondary_teams")
        )
        auto_response_changes += int(
            left.get("auto_response_policy") != right.get("auto_response_policy")
            or left.get("auto_response_template_id")
            != right.get("auto_response_template_id")
        )
        bypass_changes += int(
            left.get("model_eligibility") != right.get("model_eligibility")
        )
    old_mismatch = set(active_mismatches)
    new_mismatch = set(candidate_mismatches)
    return {
        "decisions_changed": changed,
        "decision_change_count": len(changed),
        "priority_increases": priority_increases,
        "priority_decreases": priority_decreases,
        "route_changes": route_changes,
        "primary_or_secondary_team_changes": team_changes,
        "auto_response_changes": auto_response_changes,
        "bypass_changes": bypass_changes,
        "newly_invalid_outputs": newly_invalid,
        "resolved_mismatches": [
            {"message_id": mid, "field": field}
            for mid, field in sorted(old_mismatch - new_mismatch)
        ],
        "introduced_mismatches": [
            {"message_id": mid, "field": field}
            for mid, field in sorted(new_mismatch - old_mismatch)
        ],
    }


def activation_recommendation(
    gates: Sequence[SafetyGateResult],
    *,
    output_schema_rate: float,
    audit_schema_rate: float,
    configuration_hash_valid: bool,
    rollback_valid: bool,
    change_impact: Mapping[str, object],
) -> dict[str, object]:
    blockers = [item.gate_id for item in gates if item.locked and not item.passed]
    if output_schema_rate < 1.0:
        blockers.append("OUTPUT_SCHEMA_BELOW_100_PERCENT")
    if audit_schema_rate < 1.0:
        blockers.append("AUDIT_SCHEMA_BELOW_100_PERCENT")
    if not configuration_hash_valid:
        blockers.append("CONFIGURATION_HASH_INVALID")
    if not rollback_valid:
        blockers.append("ROLLBACK_VALIDATION_FAILED")
    if change_impact.get("newly_invalid_outputs"):
        blockers.append("NEWLY_INVALID_OUTPUTS")
    return {
        "recommendation": "block" if blockers else "eligible_for_controlled_review",
        "activation_allowed": not blockers,
        "locked_blockers": sorted(set(blockers)),
        "quality_thresholds_are_guarded": True,
        "safety_thresholds_are_locked": True,
    }


def evaluate_candidate_invariants(
    config: AppConfig,
    decisions: Mapping[str, Mapping[str, Any]],
) -> tuple[SafetyGateResult, ...]:
    """Evaluate locked invariants without activating a candidate configuration."""

    values = tuple(decisions.values())
    explicit_intent = next(
        value for value in config.vocab.intents if "permanent_self_exclusion" in value
    )
    explicit_flag = next(
        value
        for value in config.vocab.risk_flags
        if "self_exclusion" in value and "explicit" in value
    )
    return (
        SafetyGateResult(
            "C01_EXPLICIT_SELF_EXCLUSION_LOCK",
            all(
                decision.get("priority") == "critical"
                and decision.get("route") == "specialist"
                and decision.get("model_called") is False
                for decision in values
                if decision.get("intent") == explicit_intent
                or explicit_flag in decision.get("risk_flags", ())
            ),
            "candidate",
            "CANDIDATE_INVARIANT_CHECKED",
        ),
        SafetyGateResult(
            "C02_SENSITIVE_SECRET_LOCK",
            all(
                decision.get("model_eligibility") == "bypass_sensitive"
                and decision.get("model_called") is False
                for decision in values
                if {"payment_card_number", "cvv", "authentication_secret"}
                & set(decision.get("sensitive_data_types", ()))
            ),
            "candidate",
            "CANDIDATE_INVARIANT_CHECKED",
        ),
        SafetyGateResult(
            "C03_PROMPT_INJECTION_LOCK",
            all(
                decision.get("model_eligibility") == "bypass_untrusted_input"
                and decision.get("model_called") is False
                for decision in values
                if "prompt_injection_detected" in decision.get("risk_flags", ())
            ),
            "candidate",
            "CANDIDATE_INVARIANT_CHECKED",
        ),
        SafetyGateResult(
            "C04_CRITICAL_SPECIALIST_LOCK",
            all(
                decision.get("route") == "specialist"
                for decision in values
                if decision.get("priority") == "critical"
            ),
            "candidate",
            "CANDIDATE_INVARIANT_CHECKED",
        ),
        SafetyGateResult(
            "C05_AUTO_RESPONSE_LOCK",
            all(_safe_auto_response(decision, _ROUTING) for decision in values),
            "candidate",
            "CANDIDATE_INVARIANT_CHECKED",
        ),
        SafetyGateResult(
            "C06_CRITICAL_SAFETY_SIGNAL_LOCK",
            all(
                decision.get("priority") == "critical"
                and decision.get("route") == "specialist"
                and decision.get("model_called") is False
                for decision in values
                if {
                    "loss_of_control",
                    "harm_linked_closure",
                    "underage_reported",
                }
                & set(decision.get("risk_flags", ()))
            ),
            "candidate",
            "CANDIDATE_INVARIANT_CHECKED",
        ),
    )


def baseline_file_digest(path: Path) -> str:
    return sha256_file(path)


def _all_gate(
    gate_id: str,
    expected_keys: Sequence[tuple[str, str]],
    results: Mapping[tuple[str, str], Any],
    predicate: Any,
) -> SafetyGateResult:
    passed = bool(expected_keys) and all(
        key in results and predicate(results[key].decision) for key in expected_keys
    )
    return SafetyGateResult(
        gate_id,
        passed,
        "independent-holdouts",
        "FIXTURE_SET_SATISFIED" if passed else "FIXTURE_SET_FAILED",
    )


def _safe_auto_response(decision: Mapping[str, Any], routing: RoutingMap) -> bool:
    if decision.get("route") != routing.constants.auto_respond:
        return True
    return (
        decision.get("auto_response_policy") == routing.constants.allowed_template
        and decision.get("human_review_required") is False
        and decision.get("priority") in {"low", "medium"}
        and not {
            "self_exclusion_explicit",
            "underage_reported",
            "prompt_injection_detected",
            "sensitive_authentication_data",
            "loss_of_control",
        }
        & set(decision.get("risk_flags", ()))
    )


def _contains_no_action_fields(decision: Mapping[str, Any]) -> bool:
    forbidden = {
        "account_action",
        "payment_action",
        "kyc_action",
        "self_exclusion_action",
        "communication_sent",
    }
    return forbidden.isdisjoint(decision)


def _safe_market_overlay(decision: Mapping[str, Any]) -> bool:
    if decision.get("market_framework_status") == "transitional":
        return bool(decision.get("market_overlay_codes")) and bool(
            decision.get("market_applicability_note")
        )
    if decision.get("market_framework_status") == "prohibited":
        return decision.get("route") != _ROUTING.constants.auto_respond and _ROUTING.constants.market_compliance_team in (
            [decision.get("assigned_team")]
            + list(decision.get("secondary_teams") or ())
        )
    return True
