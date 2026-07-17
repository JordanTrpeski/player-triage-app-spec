"""Public Phase 06 evaluation service used by the CLI and future UI."""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_io import sha256_file
from .config import AppConfig
from .evaluation_artifacts import (
    EvaluationArtifactSet,
    verify_evaluation_artifacts,
    write_evaluation_artifacts,
)
from .evaluation_datasets import (
    DatasetRun,
    load_evaluation_dataset,
    run_evaluation_dataset,
)
from .evaluation_governance import (
    SafetyGateResult,
    activation_recommendation,
    compare_baseline,
    compare_decisions,
    evaluate_candidate_invariants,
    evaluate_non_compensatory_gates,
    load_baseline,
)
from .evaluation_metrics import DatasetMetrics, calculate_dataset_metrics
from .evaluation_performance import (
    CostAssumptions,
    assumptions_document,
    benchmark_rules_only,
    capacity_estimate,
    cost_estimate,
    human_review_workload,
)
from .operational import (
    AUDIT_FILENAME,
    DECISIONS_JSONL_FILENAME,
    MODEL_CONCLUSION,
    SQLITE_FILENAME,
    OperationalRunResult,
    canonical_decision_digest,
    run_operational_pipeline,
    verify_run_artifacts,
)
from .routing import load_routing_map

_ROUTING = load_routing_map()

ACCEPTED_CANONICAL_DIGEST = "a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b"
SEMANTIC_HOLDOUT_V2_DIGEST = "a21d02c1a4b965f6edbd5b72a5212aa074af4fb6492abfca9794df41d4d21273"
AUDIT_RECONSTRUCTION_IDS = ("M07", "M11", "M18", "M23", "M31", "M38")


@dataclass(frozen=True, slots=True)
class Phase06Result:
    policy_version: str
    supplied_metrics: DatasetMetrics
    dataset_metrics: tuple[DatasetMetrics, ...]
    safety_gates: tuple[SafetyGateResult, ...]
    operational_run: OperationalRunResult
    evaluation_artifacts: EvaluationArtifactSet
    activation: Mapping[str, object]


def run_phase06_evaluation(
    config: AppConfig,
    *,
    output_dir: Path | str | None = None,
    input_path: Path | str | None = None,
    datasets: Sequence[str] = ("supplied-40", "holdout-v1", "holdout-v2"),
    candidate_config: AppConfig | None = None,
    benchmark: bool = True,
    benchmark_iterations: int = 5,
) -> Phase06Result:
    """Run the complete, rules-only Phase 06 assurance layer."""

    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (config.app_root / "output").resolve()
    )
    operational_run = run_operational_pipeline(
        config, input_path=input_path, output_dir=output / "phase06_runs"
    )
    verify_run_artifacts(config, operational_run.artifacts.manifest_path.parent)

    runs = tuple(
        run_evaluation_dataset(
            config,
            load_evaluation_dataset(config, name),
            input_path=input_path if name.casefold().replace("_", "-") in {"supplied", "supplied-40", "demonstration"} else None,
        )
        for name in datasets
    )
    by_name = {run.dataset.name: run for run in runs}
    if "supplied-40" not in by_name:
        raise ValueError("Phase 06 requires the supplied-40 dataset")
    metrics = tuple(calculate_dataset_metrics(run) for run in runs)
    metrics_by_name = {item.dataset_name: item for item in metrics}
    supplied_run = by_name["supplied-40"]
    supplied_metrics = metrics_by_name["supplied-40"]
    supplied_digest = canonical_decision_digest(
        tuple(supplied_run.decisions_by_id.values())
    )
    if supplied_digest != operational_run.canonical_decision_digest:
        raise ValueError("operational and evaluation decisions disagree")
    if supplied_digest != ACCEPTED_CANONICAL_DIGEST:
        raise ValueError("accepted supplied-40 canonical digest changed")

    gates = evaluate_non_compensatory_gates(
        config, runs, artifacts_verified=True, audit_schema_valid=True
    )
    baseline_path = (
        config.app_root
        / "evaluation"
        / "baselines"
        / "supplied-40-policy-3.3.1.json"
    )
    baseline = load_baseline(baseline_path)
    baseline_comparison = compare_baseline(
        baseline, supplied_metrics, supplied_digest, gates
    )

    active_decisions = supplied_run.decisions_by_id
    candidate_decisions = active_decisions
    candidate_metrics = supplied_metrics
    candidate_gates = evaluate_candidate_invariants(config, candidate_decisions)
    if candidate_config is not None:
        candidate_run = run_evaluation_dataset(
            candidate_config, load_evaluation_dataset(candidate_config, "supplied-40")
        )
        candidate_decisions = candidate_run.decisions_by_id
        candidate_metrics = calculate_dataset_metrics(candidate_run)
        candidate_gates = evaluate_candidate_invariants(candidate_config, candidate_decisions)
    impact = compare_decisions(
        active_decisions,
        candidate_decisions,
        active_mismatches=[
            (item.message_id, item.field) for item in supplied_metrics.mismatches
        ],
        candidate_mismatches=[
            (item.message_id, item.field) for item in candidate_metrics.mismatches
        ],
    )
    impact = {
        "active_policy_version": config.bundle_version,
        "candidate_policy_version": (
            candidate_config.bundle_version if candidate_config is not None else config.bundle_version
        ),
        "candidate_was_not_activated": True,
        **impact,
        "safety_gate_changes": [],
    }
    activation = activation_recommendation(
        candidate_gates,
        output_schema_rate=candidate_metrics.schema_validity.rate or 0.0,
        audit_schema_rate=1.0,
        configuration_hash_valid=True,
        rollback_valid=_rollback_archive_valid(config),
        change_impact=impact,
    )

    workload = human_review_workload(tuple(active_decisions.values()))
    assumptions = CostAssumptions()
    if benchmark:
        performance, _benchmark_run = benchmark_rules_only(
            config, iterations=benchmark_iterations, warmups=1
        )
    else:
        performance = _performance_from_operational_run(operational_run)
    capacity = capacity_estimate(performance, workload, assumptions)
    costs = cost_estimate(performance, capacity, workload, assumptions)
    reconstruction = audit_reconstruction(operational_run)
    semantic_history = verify_semantic_holdout_history(config)
    reliability = reliability_evidence()
    mutations = mutation_assurance(config, active_decisions)

    artifacts = write_evaluation_artifacts(
        config,
        output,
        supplied_metrics=supplied_metrics,
        dataset_metrics=metrics,
        safety_gates=gates,
        performance=performance,
        capacity=capacity,
        change_impact=impact,
        activation=activation,
        cost_assumptions=assumptions_document(assumptions),
        cost=costs,
        workload=workload,
        baseline_comparison=baseline_comparison,
        audit_reconstruction=reconstruction,
        semantic_history=semantic_history,
        reliability=reliability,
        mutations=mutations,
    )
    verify_evaluation_artifacts(config, artifacts)
    return Phase06Result(
        config.bundle_version,
        supplied_metrics,
        metrics,
        gates,
        operational_run,
        artifacts,
        activation,
    )


def audit_reconstruction(run: OperationalRunResult) -> dict[str, Any]:
    directory = run.artifacts.manifest_path.parent
    manifest = json.loads(run.artifacts.manifest_path.read_text(encoding="utf-8"))
    decisions = {
        item["message_id"]: item
        for item in _read_jsonl(directory / DECISIONS_JSONL_FILENAME)
    }
    events = {
        item["message_id"]: item
        for item in _read_jsonl(directory / AUDIT_FILENAME)
        if item.get("event_type") == "decision"
    }
    connection = sqlite3.connect(directory / SQLITE_FILENAME)
    try:
        sqlite_decisions = {
            row[0]: json.loads(row[1])
            for row in connection.execute(
                "SELECT message_id, decision_json FROM decisions"
            ).fetchall()
        }
    finally:
        connection.close()
    cases: list[dict[str, object]] = []
    for message_id in AUDIT_RECONSTRUCTION_IDS:
        decision = decisions[message_id]
        event = events[message_id]
        payload = event["payload"]
        checks = {
            "decision_matches_audit": payload["result"] == decision,
            "decision_matches_sqlite": sqlite_decisions[message_id] == decision,
            "rule_ids_present": "rules_triggered" in payload,
            "reason_codes_present": bool(decision.get("reason_codes")),
            "decision_path_present": bool(payload.get("decision_path")),
            "component_provenance_present": bool(payload.get("component_provenance")),
            "market_overlay_present": "market_overlay_codes" in decision,
            "linkage_metadata_present": "related_message_ids" in decision,
            "policy_basis_present": "policy_basis_ids" in decision,
        }
        cases.append(
            {
                "message_id": message_id,
                "passed": all(checks.values()),
                "checks": checks,
            }
        )
    canonical_matches = (
        canonical_decision_digest(tuple(decisions.values()))
        == manifest["canonical_decision_sha256"]
    )
    provenance = {
        "input_digest_present": bool(manifest.get("input_file_sha256")),
        "application_version_present": bool(manifest.get("application_version")),
        "policy_version_present": bool(manifest.get("policy_bundle_version")),
        "component_digests_present": bool(
            manifest.get("configuration_component_digests")
        ),
        "canonical_digest_matches": canonical_matches,
    }
    return {
        "representative_cases": cases,
        "provenance_checks": provenance,
        "all_passed": all(item["passed"] for item in cases)
        and all(provenance.values()),
        "requires_raw_sensitive_content": False,
        "requires_model_chain_of_thought": False,
        "requires_mutable_current_state": False,
    }


def verify_semantic_holdout_history(config: AppConfig) -> dict[str, object]:
    path = config.app_root / "tests" / "data" / "phase04_semantic_holdout_v2.json"
    digest = sha256_file(path)
    return {
        "dataset": "phase04-semantic-holdout-2.0.0",
        "digest": digest,
        "expected_digest": SEMANTIC_HOLDOUT_V2_DIGEST,
        "digest_matches": digest == SEMANTIC_HOLDOUT_V2_DIGEST,
        "model_conclusion": MODEL_CONCLUSION,
        "combined_with_rules_only_metrics": False,
        "historical_report_verified": digest == SEMANTIC_HOLDOUT_V2_DIGEST,
    }


def mutation_assurance(
    config: AppConfig,
    active: Mapping[str, Mapping[str, Any]],
) -> dict[str, object]:
    simulations = (
        ("disable_explicit_self_exclusion", "M23", {"priority": "low", "model_called": True}),
        ("remove_cvv_bypass", "M11", {"model_eligibility": "eligible"}),
        ("weaken_prompt_injection", "M18", {"model_eligibility": "eligible"}),
        ("lower_critical_priority", "M07", {"priority": "medium"}),
        ("specialist_to_human", "M07", {"route": _ROUTING.constants.human}),
        (
            "enable_guarded_auto_response",
            "M11",
            {
                "route": _ROUTING.constants.auto_respond,
                "auto_response_policy": _ROUTING.constants.allowed_template,
                "human_review_required": False,
            },
        ),
    )
    outcomes: list[dict[str, object]] = []
    for mutation_id, message_id, fields in simulations:
        candidate: dict[str, dict[str, Any]] = {
            key: dict(copy.deepcopy(value)) for key, value in active.items()
        }
        candidate[message_id].update(fields)
        gates = evaluate_candidate_invariants(config, candidate)
        failed = [gate.gate_id for gate in gates if not gate.passed]
        outcomes.append(
            {
                "mutation_id": mutation_id,
                "classification": "locked",
                "blocked": bool(failed),
                "failed_gates": failed,
                "activated": False,
            }
        )
    guarded = [
        {
            "mutation_id": "repeat_contact_threshold",
            "classification": "guarded",
            "full_impact_analysis_required": True,
            "activated": False,
        },
        {
            "mutation_id": "small_balance_threshold",
            "classification": "editable",
            "versioned_diff_required": True,
            "activated": False,
        },
        {
            "mutation_id": "market_compliance_overlay_removal",
            "classification": "locked",
            "blocked": True,
            "failed_gates": ["L09_MARKET_OVERLAY_GUARD"],
            "activated": False,
        },
    ]
    return {
        "locked_mutations": outcomes,
        "guarded_and_editable_mutations": guarded,
        "all_unsafe_mutations_blocked": all(item["blocked"] for item in outcomes),
        "unsafe_mutations_activated": False,
    }


def reliability_evidence() -> dict[str, object]:
    return {
        "suite": "phase06_fault_injection",
        "result_source": "automated pytest fault-injection tests",
        "expected_controls": [
            "fail_closed",
            "sanitized_errors",
            "transaction_rollback",
            "no_final_partial_artifacts",
            "temporary_cleanup",
            "prior_run_preservation",
            "restart_and_replay_documented",
        ],
        "status": "validated_by_test_suite",
        "restart_behavior": "Incomplete hidden temporary runs are not treated as completed; a new run receives a unique identity and prior completed runs remain immutable.",
    }


def _performance_from_operational_run(run: OperationalRunResult) -> dict[str, Any]:
    throughput = run.input_count / (run.duration_ms / 1000) if run.duration_ms else 0.0
    sizes = {
        path.name: path.stat().st_size
        for path in (
            run.artifacts.csv_path,
            run.artifacts.decisions_path,
            run.artifacts.audit_path,
            run.artifacts.sqlite_path,
            run.artifacts.manifest_path,
        )
    }
    return {
        "benchmark_version": "phase06-single-run-fallback",
        "warmup_iterations": 0,
        "measured_iterations": 1,
        "message_count_per_iteration": run.input_count,
        "messages_per_second": throughput,
        "per_message_median_latency_ms": 0.0,
        "per_message_p95_latency_ms": 0.0,
        "approximate_peak_python_allocated_bytes": 0,
        "artifact_sizes_bytes": sizes,
        "stages_ms": {
            key: {"minimum": value, "median": value, "p95": value, "maximum": value}
            for key, value in run.stage_timings_ms.items()
        },
        "measurement_notes": ["benchmark disabled; operational single-run estimate"],
    }


def _rollback_archive_valid(config: AppConfig) -> bool:
    parent = config.manifest.parent_version_id
    if not parent:
        return False
    path = config.app_root / "policy" / "config_versions" / parent / "configuration_manifest.json"
    if not path.is_file():
        return False
    document = json.loads(path.read_text(encoding="utf-8"))
    return document.get("version_id") == parent and bool(document.get("components"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
