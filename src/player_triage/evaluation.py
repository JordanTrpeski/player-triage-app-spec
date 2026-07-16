"""Rules-only evaluation over the 40 authoritative ground-truth messages.

Runs the Phase 02 ingestion pipeline and the Phase 03 engine over every
message, then compares the five scored fields against
``policy/ground_truth_40.jsonl`` and checks the ``policy/safety_assertions.json``
hard gates. Nothing raw is emitted: comparisons are field/enum/boolean only.

The ground truth is *never* modified. Mismatches are reported for adjudication.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import AppConfig
from .engine import ClassificationResult, TriageEngine
from .pipeline import ingest as run_ingest

SCORED_FIELDS: tuple[str, ...] = ("category", "intent", "priority", "route", "assigned_team")


@dataclass(frozen=True, slots=True)
class FieldMismatch:
    message_id: str
    field: str
    expected: str
    actual: str


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    passed: bool
    detail: str


@dataclass(slots=True)
class EvaluationReport:
    total: int = 0
    agreement: dict[str, int] = field(default_factory=lambda: {f: 0 for f in SCORED_FIELDS})
    mismatches: list[FieldMismatch] = field(default_factory=list)
    gate_results: list[GateResult] = field(default_factory=list)
    schema_valid_count: int = 0
    fallback_ids: list[str] = field(default_factory=list)
    results_by_id: dict[str, ClassificationResult] = field(default_factory=dict)

    def agreement_rate(self, field_name: str) -> float:
        return self.agreement[field_name] / self.total if self.total else 0.0

    def all_gates_pass(self) -> bool:
        return all(gate.passed for gate in self.gate_results)


def load_ground_truth(config: AppConfig) -> dict[str, Mapping[str, Any]]:
    path = config.app_root / "policy" / "ground_truth_40.jsonl"
    truth: dict[str, Mapping[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        truth[record["message_id"]] = record["expected_result"]
    return truth


def run_evaluation(config: AppConfig, input_path: Path | str | None = None) -> EvaluationReport:
    engine = TriageEngine.from_config(config)
    truth = load_ground_truth(config)
    ingested = run_ingest(config, input_path=input_path)

    report = EvaluationReport()
    for message in ingested:
        result = engine.classify(message)
        report.results_by_id[message.msg_id] = result
        report.total += 1
        if result.schema_valid:
            report.schema_valid_count += 1
        if result.decision.get("processing_status") == "provisional_fallback":
            report.fallback_ids.append(message.msg_id)

        expected = truth.get(message.msg_id)
        if expected is None:
            continue
        for field_name in SCORED_FIELDS:
            exp = expected.get(field_name)
            act = result.decision.get(field_name)
            if exp == act:
                report.agreement[field_name] += 1
            else:
                report.mismatches.append(
                    FieldMismatch(message.msg_id, field_name, str(exp), str(act))
                )

    report.gate_results = evaluate_gates(config, report.results_by_id)
    return report


def evaluate_gates(
    config: AppConfig, results: Mapping[str, ClassificationResult]
) -> list[GateResult]:
    gates = config.component("safety_assertions").get("hard_gates", [])
    decisions = {mid: r.decision for mid, r in results.items()}
    out: list[GateResult] = []
    for gate in gates:
        out.append(_evaluate_single_gate(gate, decisions, results))
    return out


def _evaluate_single_gate(
    gate: Mapping[str, Any],
    decisions: Mapping[str, Mapping[str, Any]],
    results: Mapping[str, ClassificationResult],
) -> GateResult:
    gate_id = gate["id"]

    if gate.get("all_messages"):
        for mid, result in results.items():
            if not result.schema_valid:
                return GateResult(gate_id, False, f"{mid} not schema valid")
            if _has_forbidden_content(result.decision):
                return GateResult(gate_id, False, f"{mid} contains forbidden content")
        return GateResult(gate_id, True, "all messages schema-valid and sanitized")

    if "equal_fields" in gate:
        message_ids: Sequence[str] = gate["message_ids"]
        fields: Sequence[str] = gate["equal_fields"]
        reference = decisions.get(message_ids[0], {})
        for mid in message_ids[1:]:
            other = decisions.get(mid, {})
            for field_name in fields:
                if reference.get(field_name) != other.get(field_name):
                    return GateResult(
                        gate_id, False, f"{mid}.{field_name} differs from {message_ids[0]}"
                    )
        return GateResult(gate_id, True, f"{list(message_ids)} equal on {list(fields)}")

    mid = gate["message_id"]
    decision = decisions.get(mid)
    if decision is None:
        return GateResult(gate_id, False, f"{mid} not classified")

    for field_name, value in gate.get("expected", {}).items():
        if decision.get(field_name) != value:
            return GateResult(gate_id, False, f"{mid}.{field_name}={decision.get(field_name)!r} != {value!r}")
    for field_name, value in gate.get("forbidden", {}).items():
        if decision.get(field_name) == value:
            return GateResult(gate_id, False, f"{mid}.{field_name} is forbidden value {value!r}")
    for flag in gate.get("required_risk_flags", []):
        if flag not in decision.get("risk_flags", []):
            return GateResult(gate_id, False, f"{mid} missing required risk flag {flag!r}")
    for category in gate.get("forbidden_categories", []):
        if decision.get("category") == category:
            return GateResult(gate_id, False, f"{mid} has forbidden category {category!r}")
    for rid in gate.get("required_related_message_ids", []):
        if rid not in decision.get("related_message_ids", []):
            return GateResult(gate_id, False, f"{mid} missing related id {rid!r}")
    for pattern in gate.get("forbidden_output_patterns", []):
        if _pattern_in_decision(pattern, decision):
            return GateResult(gate_id, False, f"{mid} matched forbidden output pattern")
    for forbidden_field in gate.get("forbidden_output_fields", []):
        if forbidden_field in decision:
            return GateResult(gate_id, False, f"{mid} exposes forbidden field {forbidden_field!r}")

    return GateResult(gate_id, True, f"{mid} satisfies gate")


_FORBIDDEN_CONTENT_RE = re.compile(r"(?:\d[ -]?){13,19}")
_PLAYER_ID_RE = re.compile(r"\bP-\d{5}\b")


def _has_forbidden_content(decision: Mapping[str, Any]) -> bool:
    for value in decision.values():
        if isinstance(value, str) and (_FORBIDDEN_CONTENT_RE.search(value) or _PLAYER_ID_RE.search(value)):
            return True
    return False


def _pattern_in_decision(pattern: str, decision: Mapping[str, Any]) -> bool:
    try:
        compiled = re.compile(pattern)
    except re.error:
        compiled = re.compile(re.escape(pattern))
    serialized = json.dumps(decision)
    return bool(compiled.search(serialized))
