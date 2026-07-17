"""Rules-only benchmark, capacity, workload and formula-driven cost estimates."""

from __future__ import annotations

import os
import platform
import statistics
import tempfile
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import AppConfig, load_app_config
from .operational import OperationalRunResult, run_operational_pipeline
from .routing import load_routing_map

_ROUTING = load_routing_map()


@dataclass(frozen=True, slots=True)
class CostAssumptions:
    currency: str = "EUR"
    electricity_eur_per_kwh: float = 0.20
    estimated_process_power_watts: float = 65.0
    storage_eur_per_gb_month: float = 0.03
    human_agent_minutes_per_case: float = 6.0
    specialist_minutes_per_case: float = 15.0
    human_labour_eur_per_hour: float = 22.0
    retention_days: int = 365
    messages_per_day: int = 900
    hosted_api_selected: bool = False
    hypothetical_hosted_api_rate_per_million_tokens: float | None = None


def benchmark_rules_only(
    config: AppConfig,
    *,
    iterations: int = 5,
    warmups: int = 1,
) -> tuple[dict[str, Any], OperationalRunResult]:
    """Benchmark complete verified runs after warm-up, without model startup."""

    if iterations < 2 or warmups < 1:
        raise ValueError("benchmark requires at least one warm-up and two measured runs")
    startup_samples: list[float] = []
    run_samples: list[OperationalRunResult] = []
    tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix="player-triage-benchmark-") as directory:
        root = Path(directory)
        for index in range(warmups + iterations):
            startup_started = time.perf_counter()
            _ = load_app_config(config.app_root)
            startup_ms = (time.perf_counter() - startup_started) * 1000
            result = run_operational_pipeline(
                config, output_dir=root / f"iteration-{index}"
            )
            if index >= warmups:
                startup_samples.append(startup_ms)
                run_samples.append(result)
        _current, peak_bytes = tracemalloc.get_traced_memory()
        artifact_sizes = {
            path.name: path.stat().st_size
            for path in (
                run_samples[-1].artifacts.csv_path,
                run_samples[-1].artifacts.decisions_path,
                run_samples[-1].artifacts.audit_path,
                run_samples[-1].artifacts.sqlite_path,
                run_samples[-1].artifacts.manifest_path,
            )
        }
    tracemalloc.stop()

    stage_names = tuple(run_samples[0].stage_timings_ms)
    stages = {
        name: _sample_summary(
            [float(result.stage_timings_ms[name]) for result in run_samples]
        )
        for name in stage_names
    }
    duration_values = [float(result.duration_ms) for result in run_samples]
    total_messages = run_samples[0].input_count
    median_duration = statistics.median(duration_values)
    throughput = total_messages / (median_duration / 1000) if median_duration else 0.0
    per_message_values = [
        float(value)
        for result in run_samples
        for value in result.per_message_latency_ms
    ]
    profile = _system_profile()
    report = {
        "benchmark_version": "phase06-rules-only-1.0.0",
        "warmup_iterations": warmups,
        "measured_iterations": iterations,
        "message_count_per_iteration": total_messages,
        "application_startup_ms": _sample_summary(startup_samples),
        "stages_ms": stages,
        "total_pipeline_ms": _sample_summary(duration_values),
        "messages_per_second": throughput,
        "per_message_median_latency_ms": statistics.median(per_message_values),
        "per_message_p95_latency_ms": _percentile(per_message_values, 0.95),
        "approximate_peak_python_allocated_bytes": peak_bytes,
        "memory_measurement_method": "tracemalloc_python_allocations",
        "artifact_sizes_bytes": artifact_sizes,
        "system_profile": profile,
        "measurement_notes": [
            "warm-up runs excluded",
            "rules-only mode; no optional model initialization",
            "local filesystem and SQLite included",
            "not a production-scale load test",
        ],
    }
    return report, run_samples[-1]


def capacity_estimate(
    performance: Mapping[str, Any],
    workload: Mapping[str, Any],
    assumptions: CostAssumptions,
) -> dict[str, Any]:
    throughput = float(performance["messages_per_second"])
    daily = assumptions.messages_per_day
    compute_seconds = daily / throughput if throughput else 0.0
    sizes = performance["artifact_sizes_bytes"]
    run_bytes = sum(int(value) for value in sizes.values())
    scaled_day_bytes = round(run_bytes * daily / int(performance["message_count_per_iteration"]))
    return {
        "messages_per_day": daily,
        "measured_rules_only_messages_per_second": throughput,
        "estimated_total_daily_compute_seconds": compute_seconds,
        "average_required_messages_per_second_24h": daily / 86400,
        "business_hours_required_messages_per_second_8h": daily / 28800,
        "ten_x_short_burst_messages_per_second": (daily / 28800) * 10,
        "full_day_replay_seconds_at_measured_throughput": compute_seconds,
        "recommended_batch_size": 100,
        "recommended_concurrency": 1,
        "recommended_concurrency_reason": "Measured throughput exceeds all illustrative arrival scenarios; serial execution preserves deterministic ordering.",
        "likely_memory_bytes": int(performance["approximate_peak_python_allocated_bytes"]),
        "storage": {
            "estimated_bytes_per_900_message_day": scaled_day_bytes,
            "estimated_bytes_one_year": scaled_day_bytes * assumptions.retention_days,
            "by_artifact_one_day": {
                name: round(int(value) * daily / int(performance["message_count_per_iteration"]))
                for name, value in sizes.items()
            },
            "configuration_archives_assumption_bytes_per_year": 50 * 1024 * 12,
        },
        "scenarios": {
            "steady_24_hours": {"arrival_interval_seconds": 86400 / daily},
            "business_hour_concentration": {"arrival_interval_seconds": 28800 / daily},
            "ten_x_short_burst": {"assumed_duration_minutes": 15},
            "one_day_replay": {"messages": daily},
        },
        "workload_source": workload.get("source_dataset"),
        "assumptions": [
            "Linear scaling from a 40-message local benchmark.",
            "Supplied-set mix is illustrative and not statistically representative.",
            "No production-scale concurrency or endurance load test was performed.",
        ],
    }


def human_review_workload(
    decisions: Sequence[Mapping[str, Any]], *, messages_per_day: int = 900
) -> dict[str, Any]:
    count = len(decisions)
    routes = _counts(decisions, "route")
    priorities = _counts(decisions, "priority")
    teams = _counts(decisions, "assigned_team")
    markets = _counts(decisions, "market")
    bypass = sum(
        1 for decision in decisions if str(decision.get("model_eligibility", "")).startswith("bypass_")
    )
    missing = sum(bool(decision.get("missing_context")) for decision in decisions)
    repeats = sum(int(decision.get("previous_contact_count", 0)) > 0 for decision in decisions)
    multiplier = messages_per_day / count if count else 0.0
    return {
        "source_dataset": "supplied-40",
        "source_message_count": count,
        "route_counts": routes,
        "priority_counts": priorities,
        "team_counts": teams,
        "market_counts": markets,
        "auto_response_count": routes.get(_ROUTING.constants.auto_respond, 0),
        "human_agent_count": routes.get(_ROUTING.constants.human, 0),
        "specialist_count": routes.get(_ROUTING.constants.specialist, 0),
        "bypass_count": bypass,
        "missing_context_count": missing,
        "repeat_contact_count": repeats,
        "illustrative_900_per_day": {
            "route_counts": {key: round(value * multiplier, 1) for key, value in routes.items()},
            "priority_counts": {
                key: round(value * multiplier, 1) for key, value in priorities.items()
            },
            "bypass_count": round(bypass * multiplier, 1),
            "missing_context_count": round(missing * multiplier, 1),
            "repeat_contact_count": round(repeats * multiplier, 1),
        },
        "limitation": "Extrapolation from 40 supplied messages is illustrative and not statistically representative.",
    }


def cost_estimate(
    performance: Mapping[str, Any],
    capacity: Mapping[str, Any],
    workload: Mapping[str, Any],
    assumptions: CostAssumptions,
) -> dict[str, Any]:
    compute_hours = float(capacity["estimated_total_daily_compute_seconds"]) / 3600
    kwh = compute_hours * assumptions.estimated_process_power_watts / 1000
    annual_gb = float(capacity["storage"]["estimated_bytes_one_year"]) / (1024**3)
    routes = workload["illustrative_900_per_day"]["route_counts"]
    human_hours = (
        float(routes.get(_ROUTING.constants.human, 0))
        * assumptions.human_agent_minutes_per_case
        + float(routes.get(_ROUTING.constants.specialist, 0))
        * assumptions.specialist_minutes_per_case
    ) / 60
    return {
        "prototype": {
            "local_compute_eur_per_day": kwh * assumptions.electricity_eur_per_kwh,
            "annual_retention_storage_eur_per_month": annual_gb
            * assumptions.storage_eur_per_gb_month,
            "runtime_dependencies": ["Python 3.12", "SQLite", "local filesystem"],
        },
        "projected_production_infrastructure": {
            "status": "not_sized",
            "cost_drivers": [
                "availability and backup design",
                "security monitoring",
                "audit retention and restore testing",
                "deployment automation",
                "enterprise identity and access control",
            ],
        },
        "human_review": {
            "illustrative_hours_per_day": human_hours,
            "illustrative_eur_per_day": human_hours
            * assumptions.human_labour_eur_per_hour,
        },
        "optional_rejected_model_experiment": {
            "selected": False,
            "reason": "model_rejected_no_material_improvement",
            "historical_only": True,
        },
        "hypothetical_hosted_api": {
            "selected": False,
            "provider_selected": False,
            "example_rate_per_million_tokens": assumptions.hypothetical_hosted_api_rate_per_million_tokens,
            "policy_notice": "OpenAI public policy currently prevents this real-money-gambling use without explicit authorization.",
            "architecture_includes_hosted_processing": False,
        },
        "maintenance_cost_drivers": [
            "policy review and regression adjudication",
            "synthetic safety fixture maintenance",
            "dependency and operating-system patching",
            "audit evidence review",
        ],
    }


def assumptions_document(assumptions: CostAssumptions) -> dict[str, object]:
    return {
        "assumptions_version": "phase06-cost-1.0.0",
        **asdict(assumptions),
        "rates_are_configurable_examples": True,
        "no_vendor_commitment": True,
    }


def _sample_summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "minimum": min(values),
        "median": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "maximum": max(values),
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * quantile)))
    return ordered[index]


def _counts(decisions: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    output: dict[str, int] = {}
    for decision in decisions:
        key = str(decision.get(field))
        output[key] = output.get(key, 0) + 1
    return dict(sorted(output.items()))


def _system_profile() -> dict[str, object]:
    return {
        "operating_system": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
    }
