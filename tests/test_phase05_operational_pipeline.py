"""Phase 05 operational artifacts, audit, SQLite and replay controls."""

from __future__ import annotations

import builtins
import csv
import json
import re
import socket
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from player_triage.config import AppConfig, load_app_config
from player_triage.operational import (
    AUDIT_FILENAME,
    CSV_FILENAME,
    MANIFEST_FILENAME,
    MODEL_CONCLUSION,
    SQLITE_FILENAME,
    OperationalRunError,
    OperationalRunResult,
    append_human_override,
    protect_csv_formula,
    run_operational_pipeline,
    verify_run_artifacts,
)


@pytest.fixture(scope="module")
def config(app_root: Path) -> AppConfig:
    return load_app_config(app_root)


@pytest.fixture(scope="module")
def completed_run(
    config: AppConfig, tmp_path_factory: pytest.TempPathFactory
) -> OperationalRunResult:
    return run_operational_pipeline(
        config, output_dir=tmp_path_factory.mktemp("phase05-complete")
    )


def _events(run: OperationalRunResult) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in run.artifacts.audit_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_complete_40_message_pipeline_and_artifact_contracts(
    config: AppConfig, completed_run: OperationalRunResult
) -> None:
    run = completed_run
    assert (run.input_count, run.success_count, run.failure_count) == (40, 40, 0)
    assert all(decision["model_called"] is False for decision in run.decisions)
    verify_run_artifacts(config, run.artifacts.manifest_path.parent)

    manifest = json.loads(run.artifacts.manifest_path.read_text(encoding="utf-8"))
    assert manifest["processing_mode"] == "rules_only"
    assert manifest["model_enabled"] is False
    assert manifest["model_approval_status"] == "rejected"
    assert manifest["model_conclusion"] == MODEL_CONCLUSION
    assert manifest["policy_bundle_version"] == "policy-3.3.1"
    assert manifest["configuration_component_versions"] == dict(
        config.component_versions()
    )
    assert manifest["configuration_component_digests"] == dict(
        config.manifest.components
    )
    assert manifest["canonical_decision_sha256"] == run.canonical_decision_digest
    assert manifest["output_artifact_digests"] == dict(run.artifacts.digests)
    assert not _contains_machine_path(manifest)

    with run.artifacts.csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == config.component("export_contract")["csv_columns"]
    assert len(rows) == 40
    assert not set(config.component("export_contract")["excluded_columns"]).intersection(
        reader.fieldnames or []
    )

    events = _events(run)
    assert len(events) == 41
    assert sum(event["event_type"] == "decision" for event in events) == 40
    assert sum(event["event_type"] == "run_summary" for event in events) == 1
    audit_schema = config.schema_registry.ids["audit_event_schema.json"]
    output_schema = config.schema_registry.ids["output_schema.json"]
    for event in events:
        config.schema_registry.validate(audit_schema, event, component_hint="phase05_test")
        if event["event_type"] == "decision":
            config.schema_registry.validate(
                output_schema, event["payload"]["result"], component_hint="phase05_test"
            )
            assert "decision_path" in event["payload"]
            assert "rules_triggered" in event["payload"]
            assert "component_provenance" in event["payload"]

    summary = events[-1]["payload"]
    assert summary["hard_gates_passed"] is True
    assert summary["hard_gate_failures"] == []
    assert summary["metrics"]["model_call_count"] == 0
    assert len(summary["mismatches"]) == 1

    decisions = {decision["message_id"]: decision for decision in run.decisions}
    assert set(decisions["M11"]["sensitive_data_types"]) >= {
        "payment_card_number",
        "cvv",
    }
    assert decisions["M11"]["model_called"] is False
    assert decisions["M18"]["model_eligibility"] == "bypass_untrusted_input"
    assert decisions["M23"]["intent"] == "explicit_permanent_self_exclusion"
    assert decisions["M23"]["model_called"] is False
    assert "M09" in decisions["M31"]["related_message_ids"]
    assert decisions["M38"]["identity_document_referenced"] is True
    assert decisions["M38"]["attachment_received"] is False

    connection = sqlite3.connect(run.artifacts.sqlite_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM decisions").fetchone() == (40,)
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone() == (41,)
        assert connection.execute("SELECT COUNT(*) FROM evaluation_summaries").fetchone() == (1,)
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        assert {
            "idx_decisions_category",
            "idx_decisions_priority",
            "idx_decisions_team",
            "idx_audit_configuration",
        }.issubset(indexes)
    finally:
        connection.close()


def test_rules_only_replay_is_substantively_deterministic(
    config: AppConfig, completed_run: OperationalRunResult, tmp_path: Path
) -> None:
    replay = run_operational_pipeline(config, output_dir=tmp_path)
    assert replay.run_id != completed_run.run_id
    assert replay.canonical_decision_digest == completed_run.canonical_decision_digest
    assert replay.decisions == completed_run.decisions
    assert replay.artifacts.csv_path.read_bytes() == completed_run.artifacts.csv_path.read_bytes()
    replay_decisions = [
        event["payload"]["result"]
        for event in _events(replay)
        if event["event_type"] == "decision"
    ]
    assert tuple(replay_decisions) == completed_run.decisions


def test_rejected_model_mode_cannot_be_activated(
    config: AppConfig, tmp_path: Path
) -> None:
    with pytest.raises(OperationalRunError, match="rules_only"):
        run_operational_pipeline(config, output_dir=tmp_path, mode="local_model")
    assert list(tmp_path.iterdir()) == []


def test_rules_only_run_uses_no_network_or_optional_runtime_and_supports_foreign_cwd(
    config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "llama_cpp" or name.startswith("llama_cpp."):
            raise AssertionError("optional runtime imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", blocked_network)
    monkeypatch.setattr(socket, "create_connection", blocked_network)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.chdir(tmp_path)
    run = run_operational_pipeline(
        config,
        input_path=config.app_root / "input" / "dataset_player_messages.csv",
        output_dir=tmp_path / "out",
    )
    assert run.success_count == 40
    assert all(decision["model_called"] is False for decision in run.decisions)


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_formula_injection_prefixes_are_neutralized(prefix: str) -> None:
    protected = protect_csv_formula(prefix + "synthetic")
    assert protected.startswith("'")
    assert not protected.startswith(prefix)


def test_message_failure_continues_safely(
    config: AppConfig, tmp_path: Path
) -> None:
    real_engine = __import__("player_triage.engine", fromlist=["TriageEngine"]).TriageEngine.from_config(
        config
    )

    class OneFailureEngine:
        def classify(self, message: object) -> object:
            if getattr(message, "msg_id") == "M20":
                raise RuntimeError("synthetic classification failure")
            return real_engine.classify(message)

        def build_decision_audit_event(self, *args: object, **kwargs: object) -> object:
            return real_engine.build_decision_audit_event(*args, **kwargs)

        def close(self) -> None:
            real_engine.close()

    run = run_operational_pipeline(
        config,
        output_dir=tmp_path,
        engine_factory=lambda _config: OneFailureEngine(),  # type: ignore[arg-type,return-value]
    )
    assert (run.success_count, run.failure_count) == (39, 1)
    events = _events(run)
    failure_events = [event for event in events if event["event_type"] == "error_fallback"]
    assert len(failure_events) == 1
    assert failure_events[0]["message_id"] == "M20"
    assert len([event for event in events if event["event_type"] == "decision"]) == 39


@pytest.mark.parametrize("failure_kind", ["output", "database"])
def test_atomic_failure_cleans_temporary_artifacts_and_preserves_failure_record(
    config: AppConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    import player_triage.operational as operational

    if failure_kind == "output":
        monkeypatch.setattr(
            operational,
            "_write_audit_atomic",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic")),
        )
    else:
        monkeypatch.setattr(operational, "_SQLITE_INDEXES", "CREATE INVALID SQL;")

    with pytest.raises(OperationalRunError):
        run_operational_pipeline(config, output_dir=tmp_path)
    assert not list(tmp_path.glob(".*.tmp"))
    assert not list(tmp_path.glob("run-*"))
    failure_records = list((tmp_path / "failures").glob("*.json"))
    assert len(failure_records) == 1
    record = json.loads(failure_records[0].read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert record["sanitized_error"] == "RUN_FAILED_CLOSED"


def test_append_only_human_override_preserves_original_decision(
    config: AppConfig, tmp_path: Path
) -> None:
    run = run_operational_pipeline(config, output_dir=tmp_path / "runs")
    original = next(decision for decision in run.decisions if decision["message_id"] == "M40")
    after = dict(original)
    after["decision_basis"] = "human_override"
    after_path = tmp_path / "after.json"
    after_path.write_text(json.dumps(after), encoding="utf-8")

    event_id = append_human_override(
        config,
        run_dir=run.artifacts.manifest_path.parent,
        message_id="M40",
        reason_code="NEW_CONTEXT_AVAILABLE",
        after_decision_path=after_path,
    )
    assert event_id
    events = _events(run)
    assert events[-1]["event_type"] == "human_override"
    assert events[-1]["payload"]["before"] == original
    assert events[-1]["payload"]["after"] == after

    connection = sqlite3.connect(run.artifacts.sqlite_path)
    try:
        stored = connection.execute(
            "SELECT decision_json FROM decisions WHERE message_id = ?", ("M40",)
        ).fetchone()
        assert stored is not None and json.loads(stored[0]) == original
        assert connection.execute("SELECT COUNT(*) FROM human_overrides").fetchone() == (1,)
    finally:
        connection.close()
    verify_run_artifacts(config, run.artifacts.manifest_path.parent)


def test_artifact_digest_tampering_fails_closed(
    config: AppConfig, tmp_path: Path
) -> None:
    run = run_operational_pipeline(config, output_dir=tmp_path)
    run.artifacts.csv_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(OperationalRunError, match="digest"):
        verify_run_artifacts(config, run.artifacts.manifest_path.parent)


def _contains_machine_path(document: object) -> bool:
    serialized = json.dumps(document)
    return bool(
        re.search(r"[A-Za-z]:[\\/]", serialized)
        or re.search(r"/(?:Users|home)/", serialized)
        or re.search(r"(?i)\.gguf", serialized)
    )


def test_output_files_are_named_by_authoritative_artifact_contract(
    completed_run: OperationalRunResult,
) -> None:
    assert completed_run.artifacts.csv_path.name == CSV_FILENAME
    assert completed_run.artifacts.audit_path.name == AUDIT_FILENAME
    assert completed_run.artifacts.sqlite_path.name == SQLITE_FILENAME
    assert completed_run.artifacts.manifest_path.name == MANIFEST_FILENAME
