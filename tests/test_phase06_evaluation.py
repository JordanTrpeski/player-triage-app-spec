"""Phase 06 evaluation, governance, assurance and cost tests."""

from __future__ import annotations

import builtins
import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest

from player_triage.artifact_io import atomic_write_text
from player_triage.config import AppConfig, load_app_config
from player_triage.evaluation_artifacts import verify_evaluation_artifacts
from player_triage.evaluation_datasets import (
    load_evaluation_dataset,
    run_evaluation_dataset,
)
from player_triage.evaluation_governance import (
    activation_recommendation,
    compare_decisions,
    evaluate_candidate_invariants,
    load_baseline,
)
from player_triage.evaluation_metrics import calculate_dataset_metrics
from player_triage.evaluation_performance import (
    CostAssumptions,
    benchmark_rules_only,
    capacity_estimate,
    cost_estimate,
    human_review_workload,
)
from player_triage.evaluation_service import Phase06Result, run_phase06_evaluation
from player_triage.operational import OperationalRunError, run_operational_pipeline


@pytest.fixture(scope="module")
def config(app_root: Path) -> AppConfig:
    return load_app_config(app_root)


@pytest.fixture(scope="module")
def phase06(
    config: AppConfig, tmp_path_factory: pytest.TempPathFactory
) -> Phase06Result:
    return run_phase06_evaluation(
        config,
        output_dir=tmp_path_factory.mktemp("phase06"),
        benchmark=False,
    )


def test_supplied_set_preserves_exact_accepted_mismatch(phase06: Phase06Result) -> None:
    metrics = phase06.supplied_metrics
    assert metrics.message_count == 40
    assert metrics.schema_validity.matches == 40
    assert metrics.semantic_validity.matches == 40
    assert [(item.message_id, item.field) for item in metrics.mismatches] == [
        ("M22", "intent")
    ]
    assert metrics.agreement["category"].matches == 40
    assert metrics.agreement["intent"].matches == 39
    assert metrics.model_call_count == 0
    assert metrics.diagnostic_differences


def test_holdout_sets_are_reported_separately(phase06: Phase06Result) -> None:
    by_name = {item.dataset_name: item for item in phase06.dataset_metrics}
    assert set(by_name) == {"supplied-40", "holdout-v1", "holdout-v2"}
    assert by_name["holdout-v1"].message_count == 25
    assert by_name["holdout-v2"].message_count == 18
    assert by_name["holdout-v2"].schema_validity.matches == 18


def test_all_non_compensatory_gates_pass(phase06: Phase06Result) -> None:
    assert len(phase06.safety_gates) >= 15
    assert all(item.passed for item in phase06.safety_gates)
    assert phase06.activation["activation_allowed"] is True


def test_baseline_is_versioned_and_current(phase06: Phase06Result, config: AppConfig) -> None:
    baseline = load_baseline(
        config.app_root
        / "evaluation"
        / "baselines"
        / "supplied-40-policy-3.3.1.json"
    )
    assert baseline.status == "accepted"
    assert baseline.canonical_decision_digest == phase06.operational_run.canonical_decision_digest
    comparison = json.loads(
        phase06.evaluation_artifacts.paths["baseline_comparison.json"].read_text(
            encoding="utf-8"
        )
    )
    assert comparison["passed"] is True


def test_change_impact_and_locked_activation_block_unsafe_candidate(
    phase06: Phase06Result, config: AppConfig,
) -> None:
    active = {item["message_id"]: item for item in phase06.operational_run.decisions}
    candidate = {key: dict(value) for key, value in active.items()}
    candidate["M23"]["priority"] = "low"
    candidate["M23"]["model_called"] = True
    impact = compare_decisions(active, candidate)
    gates = evaluate_candidate_invariants(config, candidate)
    recommendation = activation_recommendation(
        gates,
        output_schema_rate=1.0,
        audit_schema_rate=1.0,
        configuration_hash_valid=True,
        rollback_valid=True,
        change_impact=impact,
    )
    assert impact["decision_change_count"] == 1
    assert recommendation["activation_allowed"] is False
    assert recommendation["locked_blockers"]


def test_evaluation_artifacts_are_atomic_structured_and_sanitized(
    phase06: Phase06Result, config: AppConfig
) -> None:
    required = {
        "evaluation_summary.json",
        "mismatch_report.jsonl",
        "mismatch_report.csv",
        "confusion_matrix.csv",
        "safety_gate_results.json",
        "performance_results.json",
        "capacity_estimate.json",
        "change_impact.json",
        "activation_recommendation.json",
        "evaluation_manifest.json",
    }
    assert required.issubset(phase06.evaluation_artifacts.paths)
    verify_evaluation_artifacts(config, phase06.evaluation_artifacts)
    blob = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in phase06.evaluation_artifacts.paths.values()
        if path.suffix in {".json", ".jsonl", ".csv", ".md"}
    )
    assert not re.search(r"\bP-\d{5}\b", blob)
    assert all(key not in blob for key in ('"subject"', '"body"', '"raw_text"'))


def test_audit_reconstruction_and_historical_semantic_evidence(
    phase06: Phase06Result,
) -> None:
    reconstruction = json.loads(
        phase06.evaluation_artifacts.paths["audit_reconstruction.json"].read_text(
            encoding="utf-8"
        )
    )
    history = json.loads(
        phase06.evaluation_artifacts.paths["semantic_holdout_history.json"].read_text(
            encoding="utf-8"
        )
    )
    assert reconstruction["all_passed"] is True
    assert [item["message_id"] for item in reconstruction["representative_cases"]] == [
        "M07",
        "M11",
        "M18",
        "M23",
        "M31",
        "M38",
    ]
    assert history["historical_report_verified"] is True
    assert history["combined_with_rules_only_metrics"] is False


def test_workload_capacity_and_cost_formulas(phase06: Phase06Result) -> None:
    decisions = phase06.operational_run.decisions
    workload = human_review_workload(decisions)
    assumptions = CostAssumptions()
    performance = json.loads(
        phase06.evaluation_artifacts.paths["performance_results.json"].read_text(
            encoding="utf-8"
        )
    )
    capacity = capacity_estimate(performance, workload, assumptions)
    costs = cost_estimate(performance, capacity, workload, assumptions)
    assert sum(workload["route_counts"].values()) == 40
    assert capacity["messages_per_day"] == 900
    assert capacity["recommended_concurrency"] == 1
    assert costs["hypothetical_hosted_api"]["selected"] is False
    assert costs["optional_rejected_model_experiment"]["selected"] is False


def test_repeated_benchmark_structure(config: AppConfig) -> None:
    report, run = benchmark_rules_only(config, iterations=2, warmups=1)
    assert report["measured_iterations"] == 2
    assert report["warmup_iterations"] == 1
    assert report["messages_per_second"] > 0
    assert {
        "input_loading",
        "processing",
        "decision_and_audit_export",
        "sqlite_write",
        "verification",
    }.issubset(report["stages_ms"])
    assert run.success_count == 40


def test_atomic_rename_failure_leaves_no_final_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import player_triage.artifact_io as artifact_io

    target = tmp_path / "evaluation.json"
    monkeypatch.setattr(
        artifact_io.os,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic")),
    )
    with pytest.raises(OSError):
        atomic_write_text(target, "{}\n")
    assert not target.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_output_directory_unavailable_fails_closed(
    config: AppConfig, tmp_path: Path
) -> None:
    unavailable = tmp_path / "not-a-directory"
    unavailable.write_text("synthetic", encoding="utf-8")
    with pytest.raises(OperationalRunError, match="unavailable"):
        run_operational_pipeline(config, output_dir=unavailable)


def test_rules_only_evaluation_has_no_network_model_or_cwd_dependency(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> Any:
        if name == "llama_cpp" or name.startswith("llama_cpp."):
            raise AssertionError("optional model runtime imported")
        return original_import(name, *args, **kwargs)

    def blocked_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(socket, "socket", blocked_network)
    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.chdir(tmp_path)
    dataset = load_evaluation_dataset(config, "supplied-40")
    run = run_evaluation_dataset(config, dataset)
    metrics = calculate_dataset_metrics(run)
    assert metrics.schema_validity.matches == 40
    assert metrics.model_call_count == 0


def test_mutation_artifact_blocks_every_locked_mutation(phase06: Phase06Result) -> None:
    document = json.loads(
        phase06.evaluation_artifacts.paths["mutation_results.json"].read_text(
            encoding="utf-8"
        )
    )
    assert document["all_unsafe_mutations_blocked"] is True
    assert document["unsafe_mutations_activated"] is False
