"""Versioned, isolated evaluation dataset loading and execution."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_io import sha256_file, stable_json
from .config import AppConfig
from .engine import ClassificationResult, TriageEngine
from .pipeline import ingest as run_ingest

INPUT_COLUMNS: tuple[str, ...] = (
    "msg_id",
    "received_utc",
    "channel",
    "market",
    "player_id",
    "vip_tier",
    "language",
    "subject",
    "body",
)


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    name: str
    version: str
    digest: str
    expected_by_id: Mapping[str, Mapping[str, Any]]
    safety_by_id: Mapping[str, Mapping[str, Any]]
    source_path: Path
    cases: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetRun:
    dataset: EvaluationDataset
    results_by_id: Mapping[str, ClassificationResult]
    processing_failures: tuple[str, ...]
    per_message_latency_ms: Mapping[str, float]

    @property
    def decisions_by_id(self) -> Mapping[str, Mapping[str, Any]]:
        return {key: value.decision for key, value in self.results_by_id.items()}


def load_evaluation_dataset(config: AppConfig, name: str) -> EvaluationDataset:
    """Load one frozen dataset without combining it with any other set."""

    normalized = name.casefold().replace("_", "-")
    if normalized in {"supplied", "supplied-40", "demonstration"}:
        path = config.app_root / "policy" / "ground_truth_40.jsonl"
        records = tuple(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        expected = {
            str(item["message_id"]): item["expected_result"] for item in records
        }
        return EvaluationDataset(
            name="supplied-40",
            version="ground-truth-40-v3.0",
            digest=sha256_file(path),
            expected_by_id=expected,
            safety_by_id={},
            source_path=config.app_root / "input" / "dataset_player_messages.csv",
        )

    files = {
        "holdout-v1": ("synthetic_holdout.json", "holdout-v1"),
        "holdout-v2": ("holdout_v2.json", "holdout-v2"),
    }
    if normalized not in files:
        raise ValueError(f"unsupported evaluation dataset: {name}")
    filename, version = files[normalized]
    path = config.app_root / "tests" / "data" / filename
    document = json.loads(path.read_text(encoding="utf-8"))
    cases = tuple(document["cases"])
    expected = {str(case["msg_id"]): case["expected"] for case in cases}
    safety = {
        str(case["msg_id"]): case.get("safety", {})
        for case in cases
        if case.get("safety")
    }
    return EvaluationDataset(
        name=normalized,
        version=version,
        digest=sha256_file(path),
        expected_by_id=expected,
        safety_by_id=safety,
        source_path=path,
        cases=cases,
    )


def run_evaluation_dataset(
    config: AppConfig,
    dataset: EvaluationDataset,
    *,
    input_path: Path | str | None = None,
) -> DatasetRun:
    """Run one dataset in rules-only mode and retain sanitized decisions only."""

    import time

    if dataset.name == "supplied-40":
        source = Path(input_path) if input_path is not None else dataset.source_path
        return _classify_source(config, dataset, source)

    with tempfile.TemporaryDirectory(prefix="player-triage-eval-") as directory:
        source = Path(directory) / f"{dataset.name}.csv"
        with source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(INPUT_COLUMNS))
            writer.writeheader()
            for case in dataset.cases:
                writer.writerow({column: case[column] for column in INPUT_COLUMNS})
        started = time.perf_counter()
        result = _classify_source(config, dataset, source)
        _ = started
        return result


def _classify_source(
    config: AppConfig, dataset: EvaluationDataset, source: Path
) -> DatasetRun:
    import time

    engine = TriageEngine.from_config(config, mode="rules_only")
    results: dict[str, ClassificationResult] = {}
    failures: list[str] = []
    latencies: dict[str, float] = {}
    try:
        for message in run_ingest(config, input_path=source):
            started = time.perf_counter()
            try:
                result = engine.classify(message)
            except Exception:
                failures.append(message.msg_id)
                continue
            latencies[message.msg_id] = (time.perf_counter() - started) * 1000
            results[message.msg_id] = result
    finally:
        engine.close()
    return DatasetRun(dataset, results, tuple(sorted(failures)), latencies)


def combined_dataset_digest(datasets: Sequence[EvaluationDataset]) -> str:
    """Digest dataset identities only; never serialize source messages."""

    identities = [
        {"name": item.name, "version": item.version, "digest": item.digest}
        for item in sorted(datasets, key=lambda value: value.name)
    ]
    return hashlib.sha256(stable_json(identities).encode("utf-8")).hexdigest()

