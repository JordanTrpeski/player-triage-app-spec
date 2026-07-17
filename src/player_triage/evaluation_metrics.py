"""Reproducible policy metrics and sanitized error analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Mapping, Sequence

from .evaluation_datasets import DatasetRun
from .routing import load_routing_map

EXACT_FIELDS: tuple[str, ...] = (
    "category",
    "intent",
    "priority",
    "route",
    "assigned_team",
    "secondary_teams",
    "auto_response_policy",
    "auto_response_template_id",
    "human_review_required",
    "model_eligibility",
    "attachment_received",
    "attachment_referenced",
    "identity_document_referenced",
    "related_message_ids",
    "first_contact_message_id",
    "previous_contact_count",
    "risk_flags",
    "reason_codes",
)

DIAGNOSTIC_FIELDS: frozenset[str] = frozenset(
    {"secondary_teams", "risk_flags", "reason_codes"}
)

PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_ROUTING = load_routing_map()
ROUTE_ORDER = {
    _ROUTING.constants.auto_respond: 0,
    _ROUTING.constants.human: 1,
    _ROUTING.constants.specialist: 2,
}


@dataclass(frozen=True, slots=True)
class AgreementMetric:
    matches: int
    total: int
    rate: float | None


@dataclass(frozen=True, slots=True)
class LabelMetric:
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float | None
    recall: float | None
    f1: float | None


@dataclass(frozen=True, slots=True)
class MismatchRecord:
    message_id: str
    field: str
    expected: object
    actual: object
    applicable_rule_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    dataset_name: str
    adjudication_status: str


@dataclass(frozen=True, slots=True)
class DatasetMetrics:
    dataset_name: str
    dataset_version: str
    dataset_digest: str
    message_count: int
    agreement: Mapping[str, AgreementMetric]
    category_by_label: Mapping[str, LabelMetric]
    category_macro_f1: float | None
    secondary_intent: LabelMetric
    schema_validity: AgreementMetric
    semantic_validity: AgreementMetric
    fallback_rate: AgreementMetric
    processing_failure_rate: AgreementMetric
    high_risk_recall: AgreementMetric
    false_negative_high_risk_ids: tuple[str, ...]
    model_bypass_rate: AgreementMetric
    manual_review_rate: AgreementMetric
    model_call_count: int
    median_latency_ms: float
    p95_latency_ms: float
    mismatches: tuple[MismatchRecord, ...]
    diagnostic_differences: tuple[MismatchRecord, ...]
    confusion_matrix: Mapping[str, Mapping[str, int]]
    error_analysis: Mapping[str, tuple[MismatchRecord, ...]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_dataset_metrics(run: DatasetRun) -> DatasetMetrics:
    expected_by_id = run.dataset.expected_by_id
    result_by_id = run.results_by_id
    agreement_counts: dict[str, list[int]] = {field: [0, 0] for field in EXACT_FIELDS}
    mismatches: list[MismatchRecord] = []
    diagnostic_differences: list[MismatchRecord] = []
    categories = sorted(
        {
            str(expected.get("category"))
            for expected in expected_by_id.values()
            if expected.get("category") is not None
        }
        | {
            str(result.decision.get("category")) for result in result_by_id.values()
        }
    )
    confusion: dict[str, dict[str, int]] = {
        expected: {actual: 0 for actual in categories} for expected in categories
    }
    secondary_expected: list[set[str]] = []
    secondary_actual: list[set[str]] = []

    for message_id in sorted(expected_by_id):
        expected = expected_by_id[message_id]
        result = result_by_id.get(message_id)
        if result is None:
            continue
        actual = result.decision
        expected_category = expected.get("category")
        actual_category = actual.get("category")
        if expected_category is not None and actual_category is not None:
            confusion[str(expected_category)][str(actual_category)] += 1
        rule_ids = tuple(
            sorted(
                set(result.matched_pre_model)
                | set(result.matched_post_semantic)
                | set(result.matched_derived)
                | set(result.baseline_rule_ids)
                | set(result.refinement_ids)
            )
        )
        reason_codes = tuple(str(value) for value in actual.get("reason_codes", ()))
        for field_name in EXACT_FIELDS:
            if field_name not in expected:
                continue
            agreement_counts[field_name][1] += 1
            expected_value = _normalized(expected.get(field_name))
            actual_value = _normalized(actual.get(field_name))
            if expected_value == actual_value:
                agreement_counts[field_name][0] += 1
            else:
                record = MismatchRecord(
                        message_id=message_id,
                        field=field_name,
                        expected=expected_value,
                        actual=actual_value,
                        applicable_rule_ids=rule_ids,
                        reason_codes=reason_codes,
                        dataset_name=run.dataset.name,
                        adjudication_status=(
                            "diagnostic_non_baseline_difference"
                            if field_name in DIAGNOSTIC_FIELDS
                            else (
                                "approved_baseline_mismatch"
                                if run.dataset.name == "supplied-40"
                                and message_id == "M22"
                                and field_name == "intent"
                                else "unadjudicated"
                            )
                        ),
                    )
                if field_name in DIAGNOSTIC_FIELDS:
                    diagnostic_differences.append(record)
                else:
                    mismatches.append(record)
        if "secondary_intents" in expected:
            secondary_expected.append(set(expected.get("secondary_intents") or ()))
            secondary_actual.append(set(actual.get("secondary_intents") or ()))

    agreement = {
        field: _agreement(matches, total)
        for field, (matches, total) in agreement_counts.items()
    }
    category_by_label = _label_metrics(confusion, categories)
    f1_values = [value.f1 for value in category_by_label.values() if value.f1 is not None]
    secondary = _set_metric(secondary_expected, secondary_actual)
    total_expected = len(expected_by_id)
    schema_valid = sum(1 for value in result_by_id.values() if value.schema_valid)
    semantic_valid = sum(
        1 for value in result_by_id.values() if not value.semantic_violations
    )
    fallback_count = sum(
        1
        for value in result_by_id.values()
        if value.decision.get("processing_status") == "provisional_fallback"
    )
    bypass_count = sum(
        1
        for value in result_by_id.values()
        if str(value.decision.get("model_eligibility", "")).startswith("bypass_")
    )
    manual_count = sum(
        1
        for value in result_by_id.values()
        if value.decision.get("human_review_required") is True
    )
    high_risk_ids = {
        message_id
        for message_id, expected in expected_by_id.items()
        if expected.get("priority") == "critical"
    }
    high_risk_hits = {
        message_id
        for message_id in high_risk_ids
        if message_id in result_by_id
        and result_by_id[message_id].decision.get("priority") == "critical"
    }
    latency_values = sorted(run.per_message_latency_ms.values())
    analysis = _error_analysis(tuple(mismatches + diagnostic_differences))
    return DatasetMetrics(
        dataset_name=run.dataset.name,
        dataset_version=run.dataset.version,
        dataset_digest=run.dataset.digest,
        message_count=total_expected,
        agreement=agreement,
        category_by_label=category_by_label,
        category_macro_f1=sum(f1_values) / len(f1_values) if f1_values else None,
        secondary_intent=secondary,
        schema_validity=_agreement(schema_valid, total_expected),
        semantic_validity=_agreement(semantic_valid, total_expected),
        fallback_rate=_rate_metric(fallback_count, total_expected),
        processing_failure_rate=_rate_metric(len(run.processing_failures), total_expected),
        high_risk_recall=_agreement(len(high_risk_hits), len(high_risk_ids)),
        false_negative_high_risk_ids=tuple(sorted(high_risk_ids - high_risk_hits)),
        model_bypass_rate=_rate_metric(bypass_count, total_expected),
        manual_review_rate=_rate_metric(manual_count, total_expected),
        model_call_count=sum(
            1 for value in result_by_id.values() if value.decision.get("model_called") is True
        ),
        median_latency_ms=median(latency_values) if latency_values else 0.0,
        p95_latency_ms=_percentile(latency_values, 0.95),
        mismatches=tuple(mismatches),
        diagnostic_differences=tuple(diagnostic_differences),
        confusion_matrix=confusion,
        error_analysis=analysis,
    )


def _normalized(value: object) -> object:
    if isinstance(value, list):
        return tuple(sorted(str(item) for item in value))
    return value


def _agreement(matches: int, total: int) -> AgreementMetric:
    return AgreementMetric(matches, total, matches / total if total else None)


def _rate_metric(count: int, total: int) -> AgreementMetric:
    return AgreementMetric(count, total, count / total if total else None)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _label_metrics(
    confusion: Mapping[str, Mapping[str, int]], labels: Sequence[str]
) -> dict[str, LabelMetric]:
    output: dict[str, LabelMetric] = {}
    for label in labels:
        tp = confusion.get(label, {}).get(label, 0)
        fp = sum(confusion.get(other, {}).get(label, 0) for other in labels if other != label)
        fn = sum(value for other, value in confusion.get(label, {}).items() if other != label)
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        output[label] = LabelMetric(tp, fp, fn, precision, recall, _f1(precision, recall))
    return output


def _set_metric(expected: Sequence[set[str]], actual: Sequence[set[str]]) -> LabelMetric:
    tp = sum(len(left & right) for left, right in zip(expected, actual, strict=True))
    fp = sum(len(right - left) for left, right in zip(expected, actual, strict=True))
    fn = sum(len(left - right) for left, right in zip(expected, actual, strict=True))
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return LabelMetric(tp, fp, fn, precision, recall, _f1(precision, recall))


def _error_analysis(
    mismatches: tuple[MismatchRecord, ...],
) -> dict[str, tuple[MismatchRecord, ...]]:
    groups: dict[str, list[MismatchRecord]] = {
        "intent_mismatch": [],
        "priority_under_escalation": [],
        "priority_over_escalation": [],
        "route_under_escalation": [],
        "route_over_escalation": [],
        "team_routing_mismatch": [],
        "false_auto_response_approval": [],
        "unnecessary_specialist_escalation": [],
        "false_positive_safety_detection": [],
        "false_negative_safety_detection": [],
    }
    for mismatch in mismatches:
        if mismatch.field == "intent":
            groups["intent_mismatch"].append(mismatch)
        elif mismatch.field == "priority":
            expected = PRIORITY_ORDER.get(str(mismatch.expected), -1)
            actual = PRIORITY_ORDER.get(str(mismatch.actual), -1)
            key = "priority_under_escalation" if actual < expected else "priority_over_escalation"
            groups[key].append(mismatch)
        elif mismatch.field == "route":
            expected = ROUTE_ORDER.get(str(mismatch.expected), -1)
            actual = ROUTE_ORDER.get(str(mismatch.actual), -1)
            key = "route_under_escalation" if actual < expected else "route_over_escalation"
            groups[key].append(mismatch)
            if actual == ROUTE_ORDER[_ROUTING.constants.auto_respond]:
                groups["false_auto_response_approval"].append(mismatch)
            if actual == ROUTE_ORDER[_ROUTING.constants.specialist] and expected < actual:
                groups["unnecessary_specialist_escalation"].append(mismatch)
        elif mismatch.field in {"assigned_team", "secondary_teams"}:
            groups["team_routing_mismatch"].append(mismatch)
        elif mismatch.field == "risk_flags":
            expected_set = set(mismatch.expected if isinstance(mismatch.expected, tuple) else ())
            actual_set = set(mismatch.actual if isinstance(mismatch.actual, tuple) else ())
            if actual_set - expected_set:
                groups["false_positive_safety_detection"].append(mismatch)
            if expected_set - actual_set:
                groups["false_negative_safety_detection"].append(mismatch)
    return {key: tuple(value) for key, value in groups.items()}


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int((len(values) - 1) * quantile + 0.999999)))
    return values[index]
