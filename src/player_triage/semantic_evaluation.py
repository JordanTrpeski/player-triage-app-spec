"""Independent Phase 04 rules-only versus local-model semantic evaluation."""

from __future__ import annotations

import ctypes
import json
import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .config import AppConfig
from .detection import DetectionEngine
from .engine import ClassificationResult, TriageEngine
from .overlays import load_overlays
from .pipeline import _process_one
from .records import IngestedMessage, LinkageResult, RawMessage
from .routing import load_routing_map

SEMANTIC_FIELDS: tuple[str, ...] = (
    "category",
    "intent",
    "secondary_intents",
    "priority",
    "route",
    "assigned_team",
)

_UNSAFE_AUTO_FLAGS = frozenset(
    {
        "active_account_takeover",
        "cvv_exposed",
        "formal_complaint",
        "full_pan_exposed",
        "loss_of_control",
        "prompt_injection_detected",
        "redaction_uncertain",
        "self_exclusion_explicit",
        "self_harm_signal",
        "sensitive_authentication_data",
        "underage_reported",
        "unauthorized_card_use",
    }
)


@dataclass(frozen=True, slots=True)
class SemanticMismatch:
    message_id: str
    field: str
    expected: object
    actual: object


@dataclass(frozen=True, slots=True)
class SemanticCaseRecord:
    case_id: str
    model_called: bool
    candidate_schema_valid: bool | None
    rules_category: object
    rules_intent: object
    model_category: object
    model_intent: object
    final_category: object
    final_intent: object
    deterministic_overrides: tuple[str, ...]
    final_priority: object
    final_route: object
    final_team: object
    fallback_reason: str | None
    latency_ms: float
    retries: int


@dataclass(slots=True)
class SemanticModeReport:
    mode: str
    total: int = 0
    agreement: dict[str, int] = field(
        default_factory=lambda: {name: 0 for name in SEMANTIC_FIELDS}
    )
    mismatches: list[SemanticMismatch] = field(default_factory=list)
    schema_valid_count: int = 0
    fallback_count: int = 0
    schema_failure_count: int = 0
    malformed_output_count: int = 0
    retry_count: int = 0
    unsafe_auto_response_count: int = 0
    model_call_count: int = 0
    bypass_count: int = 0
    safety_regression_count: int = 0
    median_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    load_time_ms: float = 0.0
    memory_delta_mb: float | None = None
    results_by_id: dict[str, ClassificationResult] = field(default_factory=dict)
    case_records: dict[str, SemanticCaseRecord] = field(default_factory=dict)

    def rate(self, count: int) -> float:
        return count / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class SemanticComparison:
    holdout_version: str
    holdout_sha256: str
    rules_only: SemanticModeReport
    local_model: SemanticModeReport


def load_semantic_holdout(config: AppConfig) -> tuple[str, list[Mapping[str, Any]], str]:
    path = config.app_root / "tests" / "data" / "phase04_semantic_holdout_v2.json"
    raw_bytes = path.read_bytes()
    import hashlib

    digest = hashlib.sha256(raw_bytes).hexdigest()
    document = json.loads(raw_bytes)
    if document.get("authored_before_execution") is not True:
        raise ValueError("semantic holdout is not marked pre-authored")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("semantic holdout has no cases")
    return str(document["version"]), cases, digest


def build_semantic_messages(
    config: AppConfig, cases: list[Mapping[str, Any]]
) -> dict[str, IngestedMessage]:
    detector = DetectionEngine.from_policy(config.component("redaction_policy"))
    overlays = load_overlays(config.component("market_overlays"))
    received = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    messages: dict[str, IngestedMessage] = {}
    for index, case in enumerate(cases, start=1):
        case_id = _case_string(case, "case_id")
        if index > 99:
            raise ValueError("semantic holdout exceeds isolated operational ID capacity")
        message_id = f"M{index:02d}"
        raw = RawMessage(
            msg_id=message_id,
            received_utc=received,
            channel="email",
            market=_case_string(case, "market"),
            language=_case_string(case, "language"),
            subject="",
            body=_case_string(case, "text"),
            player_id="SYNTHETIC-EVALUATION",
            source_format="synthetic",
            source_row=index,
        )
        linkage = LinkageResult(
            msg_id=message_id,
            related_message_ids=(),
            first_contact_message_id=None,
            previous_contact_count=0,
            linkage_rule_ids=(),
        )
        messages[case_id] = _process_one(raw, detector, overlays, linkage)
    return messages


def run_semantic_mode(config: AppConfig, *, mode: str) -> SemanticModeReport:
    _version, cases, _digest = load_semantic_holdout(config)
    messages = build_semantic_messages(config, cases)
    before_rss = _resident_bytes()
    engine = TriageEngine.from_config(config, mode=mode)
    report = SemanticModeReport(mode=mode)
    latencies: list[float] = []
    for case in cases:
        case_id = _case_string(case, "case_id")
        expected = case.get("expected")
        if not isinstance(expected, Mapping):
            raise ValueError("semantic holdout expected block is invalid")
        message = messages[case_id]
        if message.eligibility.state != "eligible":
            raise ValueError(f"semantic holdout case {case_id} is not ingestion-model-eligible")
        result = engine.classify(message)
        report.results_by_id[case_id] = result
        report.total += 1
        if result.schema_valid and not result.semantic_violations:
            report.schema_valid_count += 1
        decision = result.decision
        if decision.get("processing_status") == "provisional_fallback":
            report.fallback_count += 1
        if result.model_trace.fallback_reason == "MODEL_SCHEMA_INVALID":
            report.schema_failure_count += 1
        if result.model_trace.error == "MODEL_JSON_INVALID":
            report.malformed_output_count += 1
        report.retry_count += result.model_trace.retries
        if decision.get("model_called") is True:
            report.model_call_count += 1
            latencies.append(result.model_trace.latency_ms)
        eligibility = decision.get("model_eligibility")
        if isinstance(eligibility, str) and eligibility.startswith("bypass_"):
            report.bypass_count += 1
        if _unsafe_auto_response(decision):
            report.unsafe_auto_response_count += 1
            report.safety_regression_count += 1
        if decision.get("model_called") is True and (
            not isinstance(eligibility, str) or eligibility.startswith("bypass_")
        ):
            report.safety_regression_count += 1
        model_candidate = result.model_trace.model_candidate or {}
        report.case_records[case_id] = SemanticCaseRecord(
            case_id=case_id,
            model_called=result.model_trace.called,
            candidate_schema_valid=(
                None if not result.model_trace.called else result.model_trace.model_candidate is not None
            ),
            rules_category=result.model_trace.rules_candidate.get("category"),
            rules_intent=result.model_trace.rules_candidate.get("intent"),
            model_category=model_candidate.get("category"),
            model_intent=model_candidate.get("intent"),
            final_category=decision.get("category"),
            final_intent=decision.get("intent"),
            deterministic_overrides=result.model_trace.deterministic_overrides,
            final_priority=decision.get("priority"),
            final_route=decision.get("route"),
            final_team=decision.get("assigned_team"),
            fallback_reason=result.model_trace.fallback_reason,
            latency_ms=result.model_trace.latency_ms,
            retries=result.model_trace.retries,
        )
        for field_name in SEMANTIC_FIELDS:
            expected_value = expected.get(field_name)
            actual_value = decision.get(field_name)
            if field_name == "secondary_intents":
                expected_value = tuple(expected_value or ())
                actual_value = tuple(actual_value or ())
            if expected_value == actual_value:
                report.agreement[field_name] += 1
            else:
                report.mismatches.append(
                    SemanticMismatch(case_id, field_name, expected_value, actual_value)
                )
    after_rss = _resident_bytes()
    worker_rss = getattr(engine.semantic_classifier, "worker_rss_bytes", None)
    if isinstance(worker_rss, int):
        # The native model is isolated, so its child-process working set is the
        # meaningful measurable impact rather than parent-process RSS.
        report.memory_delta_mb = worker_rss / (1024 * 1024)
    elif before_rss is not None and after_rss is not None:
        report.memory_delta_mb = max(0.0, (after_rss - before_rss) / (1024 * 1024))
    if latencies:
        report.median_latency_ms = statistics.median(latencies)
        ordered = sorted(latencies)
        report.p95_latency_ms = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    report.load_time_ms = float(getattr(engine.semantic_classifier, "load_time_ms", 0.0))
    engine.close()
    return report


def run_semantic_comparison(config: AppConfig) -> SemanticComparison:
    version, _cases, digest = load_semantic_holdout(config)
    rules = run_semantic_mode(config, mode="rules_only")
    local = run_semantic_mode(config, mode="local_model")
    return SemanticComparison(version, digest, rules, local)


def _case_string(case: Mapping[str, Any], key: str) -> str:
    value = case.get(key)
    if not isinstance(value, str):
        raise ValueError(f"semantic holdout field {key!r} is invalid")
    return value


def _unsafe_auto_response(decision: Mapping[str, Any]) -> bool:
    if decision.get("route") != load_routing_map().constants.auto_respond:
        return False
    flags = set(decision.get("risk_flags", ()))
    return bool(
        decision.get("priority") != "low"
        or decision.get("human_review_required") is not False
        or not decision.get("auto_response_template_id")
        or _UNSAFE_AUTO_FLAGS.intersection(flags)
    )


def _resident_bytes() -> int | None:
    """Best-effort process RSS without adding a monitoring dependency."""

    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
    )
    get_process_memory_info.restype = ctypes.c_int
    handle = get_current_process()
    ok = get_process_memory_info(handle, ctypes.byref(counters), counters.cb)
    return int(counters.WorkingSetSize) if ok else None
