"""End-to-end Phase 03 engine tests over the authoritative dataset.

Assertions reference messages by ID and compare enum/boolean/count fields only;
no subject/body text, player identifier or sensitive value is read or printed.
"""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path
from typing import Mapping

import pytest

from player_triage.config import AppConfig, load_app_config
from player_triage.engine import ClassificationResult, TriageEngine
from player_triage.evaluation import run_evaluation
from player_triage.pipeline import ingest as run_ingest


@pytest.fixture(scope="module")
def config(app_root: Path) -> AppConfig:
    return load_app_config(app_root)


@pytest.fixture(scope="module")
def decisions(config: AppConfig) -> dict[str, Mapping[str, object]]:
    engine = TriageEngine.from_config(config)
    out: dict[str, Mapping[str, object]] = {}
    for message in run_ingest(config):
        out[message.msg_id] = engine.classify(message).decision
    return out


# -- all 40 schema-valid ----------------------------------------------------
def test_all_forty_schema_valid(config: AppConfig) -> None:
    report = run_evaluation(config)
    assert report.total == 40
    assert report.schema_valid_count == 40


def test_all_safety_gates_pass(config: AppConfig) -> None:
    report = run_evaluation(config)
    failed = [g.gate_id for g in report.gate_results if not g.passed]
    assert failed == [], f"failed gates: {failed}"


def test_scored_agreement_thresholds(config: AppConfig) -> None:
    report = run_evaluation(config)
    # After Phase 03B deterministic coverage: category/priority/route/team are
    # exact; the only intent gap is M22 (an accepted Phase 04 semantic target).
    assert report.agreement["category"] == 40
    assert report.agreement["intent"] >= 39
    assert report.agreement["priority"] == 40
    assert report.agreement["route"] == 40
    assert report.agreement["assigned_team"] == 40


# -- required supplied cases ------------------------------------------------
def test_m07_harm_linked_closure(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M07"]
    assert d["category"] == "Responsible Gambling"
    assert d["priority"] == "critical"
    assert d["assigned_team"] == "Responsible Gambling"
    assert d["route"] == "specialist"
    assert d["model_called"] is False


def test_m11_payment_security_no_model(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M11"]
    assert d["priority"] == "critical"
    assert d["assigned_team"] == "Payments Security"
    assert d["model_eligibility"] == "bypass_sensitive"
    assert d["model_called"] is False
    assert d["category"] == "Payments & Withdrawals"
    # PAN and CVV both detected -> the specific bypass reason (matches ground truth).
    assert d["model_bypass_reason"] == "pan_and_cvv_detected"


def test_m15_underage_critical(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M15"]
    assert d["category"] == "Fraud & Compliance"
    assert d["intent"] == "underage_gambling_report"
    assert d["priority"] == "critical"
    assert "underage_reported" in d["risk_flags"]
    assert d["model_called"] is False


def test_m18_withdrawal_injection(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M18"]
    assert d["category"] == "Payments & Withdrawals"
    assert d["priority"] == "medium"
    assert d["route"] == "human"
    assert d["model_eligibility"] == "bypass_untrusted_input"
    assert d["model_called"] is False
    assert "prompt_injection_detected" in d["risk_flags"]


def test_m23_self_exclusion_german(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M23"]
    assert d["category"] == "Responsible Gambling"
    assert d["priority"] == "critical"
    assert "self_exclusion_explicit" in d["risk_flags"]
    assert d["model_called"] is False


def test_m25_formal_complaint(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M25"]
    assert d["category"] == "Complaints & Regulatory"
    assert d["route"] == "specialist"
    assert d["priority"] == "high"


def test_m29_game_dispute_attachment_reference(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M29"]
    assert d["intent"] == "game_result_dispute"
    assert d["assigned_team"] == "Game Integrity"
    assert d["attachment_received"] is False
    assert d["attachment_referenced"] is True
    assert "attachment_referenced" in d["risk_flags"]


def test_m31_repeated_complaint_linked(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M31"]
    assert d["category"] == "Complaints & Regulatory"
    assert d["priority"] == "high"
    assert d["first_contact_message_id"] == "M09"
    assert d["previous_contact_count"] == 1
    assert "M09" in d["related_message_ids"]


def test_m33_marketing_opt_out(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M33"]
    assert d["intent"] == "marketing_opt_out"
    assert d["route"] == "auto_respond"
    assert d["auto_response_template_id"] == "ACK_MARKETING_OPTOUT"


def test_m36_reopen_specialist(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M36"]
    assert d["route"] == "specialist"
    assert d["assigned_team"] == "Responsible Gambling"
    assert d["model_called"] is False


def test_m14_tax_requires_approval(decisions: Mapping[str, Mapping[str, object]]) -> None:
    d = decisions["M14"]
    assert d["route"] == "human"
    assert d["auto_response_policy"] == "requires_approval"
    assert d["auto_response_template_id"] is None


def test_m12_m27_m34_consistent(decisions: Mapping[str, Mapping[str, object]]) -> None:
    fields = ("category", "intent", "priority", "route", "assigned_team",
              "auto_response_policy", "auto_response_template_id")
    ref = {f: decisions["M12"][f] for f in fields}
    for mid in ("M27", "M34"):
        assert {f: decisions[mid][f] for f in fields} == ref
    assert ref["route"] == "auto_respond"


# -- sanitization -----------------------------------------------------------
_PAN_RE = re.compile(r"(?:\d[ -]?){13,19}")
_PLAYER_ID_RE = re.compile(r"\bP-\d{5}\b")
_FIXTURES = ("4539 1488 0343 6467", "4539148803436467", "CVV 441", "cvv 441")


def test_no_sensitive_values_in_any_decision(decisions: Mapping[str, Mapping[str, object]]) -> None:
    for mid, decision in decisions.items():
        blob = json.dumps(decision)
        assert not _PAN_RE.search(blob), mid
        assert not _PLAYER_ID_RE.search(blob), mid
        for fixture in _FIXTURES:
            assert fixture not in blob, mid


# -- foreign cwd + no network ----------------------------------------------
def test_runs_from_foreign_cwd(config: AppConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = run_evaluation(config)
    assert report.total == 40
    assert report.schema_valid_count == 40


def test_no_network_during_classification(config: AppConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted during classification")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    report = run_evaluation(config)
    assert report.total == 40
    assert report.all_gates_pass()


def test_result_path_is_sanitized(config: AppConfig) -> None:
    engine = TriageEngine.from_config(config)
    for message in run_ingest(config):
        result: ClassificationResult = engine.classify(message)
        path = result.decision_path()
        assert not _PAN_RE.search(path)
        assert not _PLAYER_ID_RE.search(path)
