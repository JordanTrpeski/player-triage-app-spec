"""Phase 07 local console, change control and rollback tests."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from player_triage.cli import app
from player_triage.configuration_manager import (
    ConfigurationManager,
    ConsoleConfigurationError,
    component_bundle_digest,
)
from player_triage.console_service import ConsoleService
from player_triage.pattern_lab import FIXTURES, run_pattern_lab


def test_console_read_models_are_structured_and_sanitized(app_root: Path) -> None:
    service = ConsoleService(app_root)
    dashboard = service.dashboard()
    assert dashboard.runtime_mode == "rules_only"
    assert dashboard.model_calls == 0
    assert dashboard.counts["success"] == 40
    assert dashboard.core_mismatch_count == 1
    assert dashboard.diagnostic_difference_count == 52

    messages = service.messages()
    assert len(messages) == 40
    m11 = next(item for item in messages if item.message_id == "M11")
    document = json.dumps(m11.decision, sort_keys=True)
    assert all(key not in m11.decision for key in ("subject", "body", "player_id"))
    assert "4539148803436467" not in document
    assert service.messages({"message_id": "M11"}) == (m11,)
    assert service.messages({"core_mismatch": True})[0].message_id == "M22"

    settings_blob = json.dumps(service.settings(), sort_keys=True)
    assert str(app_root) not in settings_blob
    assert "<app-root>" in settings_blob
    model = service.policy_components()["model_configuration"]["document"]
    assert "local_path_reference" not in model
    assert "approved_model_id" not in model
    assert "sha256" not in model


def test_draft_activation_stale_rejection_and_full_rollback(
    app_root: Path, tmp_path: Path
) -> None:
    manager = ConfigurationManager(app_root, tmp_path / "control")
    base_state = manager.active_state()
    base_digest = component_bundle_digest(app_root / "policy")

    stale = manager.create_draft("reviewer-a", "stale candidate proof")
    stale_impact = manager.impact_preview(str(stale["draft_id"]))
    assert stale_impact["activation_recommendation"]["activation_allowed"] is True

    draft = manager.create_draft("reviewer-b", "safe rationale lifecycle")
    manager.update_rationale_template(
        str(draft["draft_id"]),
        "BALANCE_RECONCILIATION",
        "A structured balance review is required; no account action is performed.",
    )
    validation = manager.validate_draft(str(draft["draft_id"]))
    assert validation["schema_valid"] is True
    assert validation["locked_changes"] == []
    impact = manager.impact_preview(str(draft["draft_id"]))
    assert len(impact["official_and_locked_gates"]) == 26
    assert all(item["passed"] for item in impact["official_and_locked_gates"])
    assert all(item["passed"] for item in impact["candidate_invariants"])
    assert impact["activation_recommendation"]["activation_allowed"] is True
    assert impact["impact"]["decision_change_count"] >= 1

    version = manager.activate(str(draft["draft_id"]), "reviewer-b", "ACTIVATE")
    assert manager.active_state()["version_id"] == version
    with pytest.raises(ConsoleConfigurationError):
        manager.activate(str(stale["draft_id"]), "reviewer-a", "ACTIVATE")
    assert manager.active_state()["version_id"] == version

    restored = manager.rollback(
        str(base_state["version_id"]),
        "reviewer-b",
        "restore accepted repository configuration",
        "ROLLBACK",
    )
    assert restored == base_state["version_id"]
    assert manager.active_state()["bundle_digest"] == base_digest
    rollback_events = [
        event
        for event in manager.control_audit_events()
        if event["event_type"] == "configuration_rollback"
    ]
    assert rollback_events[-1]["payload"]["regression_passed"] is True


def test_locked_rules_model_configuration_and_dynamic_templates_are_blocked(
    app_root: Path, tmp_path: Path
) -> None:
    manager = ConfigurationManager(app_root, tmp_path / "control")
    draft = manager.create_draft("local-reviewer", "negative controls")
    draft_id = str(draft["draft_id"])
    with pytest.raises(ConsoleConfigurationError):
        manager.update_derived_rule_field(
            draft_id, "RG_EXPLICIT_SELF_EXCLUSION", "set.priority", "low"
        )
    with pytest.raises(ConsoleConfigurationError):
        manager.update_rationale_template(
            draft_id, "BALANCE_RECONCILIATION", "Unsafe {dynamic_value}"
        )
    model_path = manager.drafts_root / draft_id / "policy" / "model_configuration.json"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    model["approval_status"] = "approved"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    rejected = manager.validate_draft(draft_id)
    assert rejected["schema_valid"] is False
    assert "model_configuration" in rejected["locked_changes"]


def test_kill_switch_is_audited_and_never_changes_rules_mode(
    app_root: Path, tmp_path: Path
) -> None:
    manager = ConfigurationManager(app_root, tmp_path / "control")
    manager.set_kill_switch(False, "local-reviewer", "CONFIRM")
    settings = manager.settings()
    assert settings["model_kill_switch_enabled"] is False
    assert settings["runtime_mode"] == "rules_only"
    event = manager.control_audit_events()[-1]
    assert event["payload"]["change_reason"] == "MODEL_KILL_SWITCH_CHANGED"


def test_pattern_lab_suppresses_synthetic_sensitive_values(app_root: Path) -> None:
    service = ConsoleService(app_root)
    fixture = next(item for item in FIXTURES if item.fixture_id == "payment-secret")
    result = run_pattern_lab(
        service.configuration.load_active_config(),
        synthetic_text=fixture.text,
        fixture_id=fixture.fixture_id,
    )
    blob = json.dumps(result.__dict__ if hasattr(result, "__dict__") else {
        field: getattr(result, field) for field in result.__dataclass_fields__
    })
    assert result.model_called is False
    assert result.detector_counts
    assert "4539" not in blob
    assert "6467" not in blob
    assert "441" not in blob


def test_streamlit_all_console_pages_render_without_exception(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every console page must render cleanly.

    The list is pinned explicitly rather than counted, so adding or removing a
    page is a deliberate, reviewable change. Phase 09 added Walkthrough (the
    landing page) and Import to the original eight, and renamed Evaluation to
    Benchmark Evaluation so its scope is stated rather than inferred.
    """

    monkeypatch.setenv("PLAYER_TRIAGE_APP_ROOT", str(app_root))
    application = app_root / "src" / "player_triage" / "ui" / "app.py"
    rendered = AppTest.from_file(str(application)).run(timeout=60)
    pages = rendered.sidebar.radio[0].options
    assert pages == [
        "Walkthrough",
        "Dashboard",
        "Import",
        "Messages",
        "Human Review",
        "Policy Studio",
        "Benchmark Evaluation",
        "Audit Explorer",
        "Configuration Versions",
        "Settings",
    ]
    for page in pages:
        rendered.sidebar.radio[0].set_value(page)
        rendered.run(timeout=60)
        assert not rendered.exception, page


def test_demo_dry_run_works_from_foreign_cwd(
    app_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["demo", "--dry-run", "--app-root", str(app_root)]
    )
    assert result.exit_code == 0, result.output
    assert "127.0.0.1" in result.output
    assert str(app_root) not in result.output


def test_console_services_have_no_network_or_optional_model_dependency(
    app_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    service = ConsoleService(app_root)
    assert service.dashboard().model_calls == 0
    assert len(service.messages()) == 40


def test_empty_and_corrupt_artifact_states_fail_closed(
    app_root: Path, tmp_path: Path
) -> None:
    empty = ConsoleService(
        app_root,
        state_root=tmp_path / "empty-control",
        output_root=tmp_path / "empty-output",
    )
    assert empty.dashboard().latest_run_status == "no verified run"
    assert empty.messages() == ()
    assert empty.evaluation_documents() == {}

    corrupt_output = tmp_path / "corrupt-output"
    corrupt_run = corrupt_output / "run"
    corrupt_run.mkdir(parents=True)
    (corrupt_run / "run_manifest.json").write_text("{bad", encoding="utf-8")
    (corrupt_run / "decisions.jsonl").write_text("{}\n", encoding="utf-8")
    (corrupt_output / "safety_gate_results.json").write_text(
        "{bad", encoding="utf-8"
    )
    corrupt = ConsoleService(
        app_root,
        state_root=tmp_path / "corrupt-control",
        output_root=corrupt_output,
    )
    assert corrupt.latest_run_dir() is None
    assert "safety" not in corrupt.evaluation_documents()


def test_streamlit_starts_on_loopback_and_serves_http(app_root: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    environment = os.environ.copy()
    environment["PLAYER_TRIAGE_APP_ROOT"] = str(app_root)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_root / "src" / "player_triage" / "ui" / "app.py"),
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}", timeout=1
                ) as response:
                    assert response.status == 200
                    break
            except OSError:
                if process.poll() is not None:
                    pytest.fail("Streamlit exited before serving the local console")
                time.sleep(0.2)
        else:
            pytest.fail("Streamlit did not become ready on loopback")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
