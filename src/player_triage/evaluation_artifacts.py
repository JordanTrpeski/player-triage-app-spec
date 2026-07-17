"""Atomic publication of sanitized Phase 06 evaluation evidence."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_io import atomic_write_json, atomic_write_text, sha256_file, stable_json
from .config import AppConfig
from .evaluation_governance import SafetyGateResult
from .evaluation_metrics import DatasetMetrics, MismatchRecord


@dataclass(frozen=True, slots=True)
class EvaluationArtifactSet:
    output_dir: Path
    paths: Mapping[str, Path]
    digests: Mapping[str, str]


def write_evaluation_artifacts(
    config: AppConfig,
    output_dir: Path,
    *,
    supplied_metrics: DatasetMetrics,
    dataset_metrics: Sequence[DatasetMetrics],
    safety_gates: Sequence[SafetyGateResult],
    performance: Mapping[str, Any],
    capacity: Mapping[str, Any],
    change_impact: Mapping[str, Any],
    activation: Mapping[str, Any],
    cost_assumptions: Mapping[str, object],
    cost: Mapping[str, Any],
    workload: Mapping[str, Any],
    baseline_comparison: Mapping[str, Any],
    audit_reconstruction: Mapping[str, Any],
    semantic_history: Mapping[str, Any],
    reliability: Mapping[str, Any],
    mutations: Mapping[str, Any],
) -> EvaluationArtifactSet:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_mismatches = tuple(
        mismatch
        for metrics in dataset_metrics
        for mismatch in (*metrics.mismatches, *metrics.diagnostic_differences)
    )
    summary = _schema_summary(config, supplied_metrics, safety_gates)
    documents: dict[str, Mapping[str, object]] = {
        "evaluation_summary.json": summary,
        "safety_gate_results.json": {
            "all_locked_gates_passed": all(item.passed for item in safety_gates),
            "results": [asdict(item) for item in safety_gates],
        },
        "performance_results.json": performance,
        "capacity_estimate.json": capacity,
        "change_impact.json": change_impact,
        "activation_recommendation.json": activation,
        "cost_assumptions.json": cost_assumptions,
        "cost_estimate.json": cost,
        "human_review_workload.json": workload,
        "baseline_comparison.json": baseline_comparison,
        "audit_reconstruction.json": audit_reconstruction,
        "semantic_holdout_history.json": semantic_history,
        "reliability_results.json": reliability,
        "mutation_results.json": mutations,
        "dataset_results.json": {
            "datasets_are_reported_separately": True,
            "results": [metrics.to_dict() for metrics in dataset_metrics],
        },
    }
    paths: dict[str, Path] = {}
    for filename, document in documents.items():
        path = output_dir / filename
        atomic_write_json(path, document)
        paths[filename] = path

    mismatch_jsonl = output_dir / "mismatch_report.jsonl"
    atomic_write_text(
        mismatch_jsonl,
        "\n".join(stable_json(asdict(item)) for item in all_mismatches)
        + ("\n" if all_mismatches else ""),
    )
    paths[mismatch_jsonl.name] = mismatch_jsonl

    mismatch_csv = output_dir / "mismatch_report.csv"
    atomic_write_text(mismatch_csv, _mismatch_csv(all_mismatches))
    paths[mismatch_csv.name] = mismatch_csv

    confusion_csv = output_dir / "confusion_matrix.csv"
    atomic_write_text(confusion_csv, _confusion_csv(supplied_metrics))
    paths[confusion_csv.name] = confusion_csv

    report_path = output_dir / "evaluation_report.md"
    atomic_write_text(
        report_path,
        _markdown_report(
            supplied_metrics,
            dataset_metrics,
            safety_gates,
            performance,
            capacity,
            workload,
            activation,
        ),
    )
    paths[report_path.name] = report_path

    digests = {name: sha256_file(path) for name, path in sorted(paths.items())}
    manifest_path = output_dir / "evaluation_manifest.json"
    manifest = {
        "evaluation_version": "phase06-1.0.0",
        "application_version": "0.1.0",
        "policy_bundle_version": config.bundle_version,
        "artifacts": {
            name: {"relative_path": name, "sha256": digest}
            for name, digest in sorted(digests.items())
        },
    }
    atomic_write_json(manifest_path, manifest)
    paths[manifest_path.name] = manifest_path
    digests[manifest_path.name] = sha256_file(manifest_path)
    return EvaluationArtifactSet(output_dir, paths, digests)


def verify_evaluation_artifacts(
    config: AppConfig, artifacts: EvaluationArtifactSet
) -> None:
    manifest = json.loads(
        artifacts.paths["evaluation_manifest.json"].read_text(encoding="utf-8")
    )
    if manifest.get("policy_bundle_version") != config.bundle_version:
        raise ValueError("evaluation policy version mismatch")
    for filename, record in manifest["artifacts"].items():
        if sha256_file(artifacts.output_dir / filename) != record["sha256"]:
            raise ValueError("evaluation artifact digest mismatch")
    summary = json.loads(
        artifacts.paths["evaluation_summary.json"].read_text(encoding="utf-8")
    )
    schema_id = config.schema_registry.ids["evaluation_summary_schema.json"]
    config.schema_registry.validate(schema_id, summary, component_hint="phase06_summary")
    for line in artifacts.paths["mismatch_report.jsonl"].read_text(
        encoding="utf-8"
    ).splitlines():
        if line:
            item = json.loads(line)
            if set(item) != {
                "message_id",
                "field",
                "expected",
                "actual",
                "applicable_rule_ids",
                "reason_codes",
                "dataset_name",
                "adjudication_status",
            }:
                raise ValueError("mismatch report contains an unexpected field")


def _schema_summary(
    config: AppConfig,
    metrics: DatasetMetrics,
    gates: Sequence[SafetyGateResult],
) -> dict[str, Any]:
    official = [item for item in gates if item.gate_id.startswith("S")]
    flat_metrics: dict[str, int | float | None] = {
        "category_exact_match": metrics.agreement["category"].matches,
        "intent_exact_match": metrics.agreement["intent"].matches,
        "priority_exact_match": metrics.agreement["priority"].matches,
        "route_exact_match": metrics.agreement["route"].matches,
        "assigned_team_exact_match": metrics.agreement["assigned_team"].matches,
        "category_macro_f1": metrics.category_macro_f1,
        "secondary_intent_precision": metrics.secondary_intent.precision,
        "secondary_intent_recall": metrics.secondary_intent.recall,
        "fallback_rate": metrics.fallback_rate.rate,
        "processing_failure_rate": metrics.processing_failure_rate.rate,
        "semantic_validity_rate": metrics.semantic_validity.rate,
        "model_call_count": metrics.model_call_count,
    }
    summary = {
        "run_id": "phase06-supplied-40-evaluation",
        "configuration_version": config.bundle_version,
        "message_count": metrics.message_count,
        "terminal_count": 0,
        "schema_valid_count": metrics.schema_validity.matches,
        "hard_gates_passed": all(item.passed for item in gates),
        "hard_gate_failures": [item.gate_id for item in gates if not item.passed],
        "metrics": flat_metrics,
        "mismatches": [asdict(item) for item in metrics.mismatches],
        "latency_ms": {
            "median": metrics.median_latency_ms,
            "p95": metrics.p95_latency_ms,
        },
        "bypass_rate": metrics.model_bypass_rate.rate or 0.0,
        "manual_review_rate": metrics.manual_review_rate.rate or 0.0,
    }
    schema_id = config.schema_registry.ids["evaluation_summary_schema.json"]
    config.schema_registry.validate(schema_id, summary, component_hint="phase06_summary")
    _ = official
    return summary


def _mismatch_csv(mismatches: Sequence[MismatchRecord]) -> str:
    stream = io.StringIO(newline="")
    fields = [
        "message_id",
        "field",
        "expected",
        "actual",
        "applicable_rule_ids",
        "reason_codes",
        "dataset_name",
        "adjudication_status",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for item in mismatches:
        row = asdict(item)
        row["expected"] = stable_json(row["expected"])
        row["actual"] = stable_json(row["actual"])
        row["applicable_rule_ids"] = ";".join(item.applicable_rule_ids)
        row["reason_codes"] = ";".join(item.reason_codes)
        writer.writerow(row)
    return stream.getvalue()


def _confusion_csv(metrics: DatasetMetrics) -> str:
    labels = sorted(metrics.confusion_matrix)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["expected_category", *labels])
    for expected in labels:
        writer.writerow(
            [expected, *(metrics.confusion_matrix[expected].get(label, 0) for label in labels)]
        )
    return stream.getvalue()


def _markdown_report(
    supplied: DatasetMetrics,
    datasets: Sequence[DatasetMetrics],
    gates: Sequence[SafetyGateResult],
    performance: Mapping[str, Any],
    capacity: Mapping[str, Any],
    workload: Mapping[str, Any],
    activation: Mapping[str, Any],
) -> str:
    lines = [
        "# Phase 06 Evaluation Report",
        "",
        "This is a synthetic demonstration evaluation, not production accuracy or compliance validation.",
        "",
        "## Dataset results (kept separate)",
        "",
        "| Dataset | Messages | Category | Intent | Schema valid | Mismatches |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for dataset_metric in datasets:
        lines.append(
            f"| {dataset_metric.dataset_name} | {dataset_metric.message_count} | "
            f"{dataset_metric.agreement['category'].matches}/{dataset_metric.agreement['category'].total} | "
            f"{dataset_metric.agreement['intent'].matches}/{dataset_metric.agreement['intent'].total} | "
            f"{dataset_metric.schema_validity.matches}/{dataset_metric.schema_validity.total} | {len(dataset_metric.mismatches)} |"
        )
    lines.extend(
        [
            "",
            "## Supplied-set approved mismatches",
            "",
        ]
    )
    for mismatch in supplied.mismatches:
        lines.append(
            f"- {mismatch.message_id} `{mismatch.field}`: expected `{mismatch.expected}`, actual `{mismatch.actual}` "
            f"({mismatch.adjudication_status})."
        )
    lines.extend(
        [
            "",
            "## Additional set-valued diagnostic differences",
            "",
            f"- {len(supplied.diagnostic_differences)} differences are reported in the machine-readable mismatch table for secondary teams, risk flags, and reason codes.",
            "- These are measured transparently but do not redefine the accepted M22-only deterministic baseline.",
        ]
    )
    lines.extend(
        [
            "",
            "## Safety and activation",
            "",
            f"- Locked gates: {sum(item.passed for item in gates)}/{len(gates)} passed.",
            f"- Activation recommendation: `{activation['recommendation']}`.",
            f"- Model calls: {supplied.model_call_count}.",
            "",
            "## Performance and capacity",
            "",
            f"- Measured rules-only throughput: {float(performance['messages_per_second']):.2f} messages/second.",
            f"- Illustrative 900-message compute time: {float(capacity['estimated_total_daily_compute_seconds']):.2f} seconds/day.",
            f"- Recommended batch/concurrency: {capacity['recommended_batch_size']} / {capacity['recommended_concurrency']}.",
            "",
            "## Human review",
            "",
            f"- Supplied set: auto={workload['auto_response_count']}, human={workload['human_agent_count']}, specialist={workload['specialist_count']}.",
            "- The 900-message/day extrapolation is illustrative and not statistically representative.",
            "",
            "No Streamlit, Policy Studio, external integration, hosted model, or autonomous action is included.",
        ]
    )
    return "\n".join(lines) + "\n"
