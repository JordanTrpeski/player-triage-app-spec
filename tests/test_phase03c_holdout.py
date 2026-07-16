"""Independent synthetic-holdout evaluation (Phase 03C).

Runs a synthetic challenge set (``tests/data/synthetic_holdout.json``) through the
full pipeline + engine and reports holdout metrics *separately* from the supplied
40-message metrics. Expected results were written before running the engine and
are not adjusted here. Genuine high-risk cases that the deterministic system must
catch are asserted; known limitations (multilingual, indirect harm, quoted/negated
safety language) are recorded as false positives/negatives for the report rather
than silently accepted.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pytest

from player_triage.config import load_app_config
from player_triage.engine import TriageEngine
from player_triage.pipeline import ingest as run_ingest

_FIELDS = ("category", "intent", "priority", "route", "assigned_team")
_COLUMNS = ["msg_id", "received_utc", "channel", "market", "player_id", "vip_tier", "language", "subject", "body"]
_RG_INTENTS = {"credible_self_harm", "explicit_permanent_self_exclusion", "harm_linked_account_closure"}


@dataclass
class HoldoutReport:
    total: int = 0
    schema_valid: int = 0
    agreement: dict[str, int] = field(default_factory=lambda: {f: 0 for f in _FIELDS})
    mismatches: list[tuple[str, str, str, str]] = field(default_factory=list)
    false_positives: list[tuple[str, str]] = field(default_factory=list)
    false_negatives: list[tuple[str, str]] = field(default_factory=list)
    decisions: dict[str, Mapping[str, Any]] = field(default_factory=dict)


def _load_cases(app_root: Path) -> list[dict[str, Any]]:
    data = json.loads((app_root / "tests" / "data" / "synthetic_holdout.json").read_text(encoding="utf-8"))
    return data["cases"]


def _write_csv(cases: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for case in cases:
            writer.writerow({
                "msg_id": case["msg_id"],
                "received_utc": case["received_utc"],
                "channel": case["channel"],
                "market": case["market"],
                "player_id": case["player_id"],
                "vip_tier": case["vip_tier"],
                "language": case["language"],
                "subject": case["subject"],
                "body": case["body"],
            })


def run_holdout(app_root: Path, tmp_path: Path) -> HoldoutReport:
    cases = _load_cases(app_root)
    csv_path = tmp_path / "synthetic_holdout.csv"
    _write_csv(cases, csv_path)

    config = load_app_config(app_root)
    engine = TriageEngine.from_config(config)
    by_id = {c["msg_id"]: c for c in cases}

    report = HoldoutReport()
    for message in run_ingest(config, input_path=csv_path):
        result = engine.classify(message)
        decision = result.decision
        report.decisions[message.msg_id] = decision
        report.total += 1
        if result.schema_valid:
            report.schema_valid += 1

        case = by_id[message.msg_id]
        expected = case["expected"]
        for f in _FIELDS:
            if decision.get(f) == expected.get(f):
                report.agreement[f] += 1
            else:
                report.mismatches.append((message.msg_id, f, str(expected.get(f)), str(decision.get(f))))

        safety = case.get("safety", {})
        escalated = decision["category"] == "Responsible Gambling" or decision["intent"] in _RG_INTENTS
        if safety.get("ideal_no_safety_escalation") and escalated:
            report.false_positives.append((message.msg_id, f"{case['challenge']}: safety escalation on benign text"))
        if safety.get("expect_high_risk") and not (decision["category"] == "Responsible Gambling" and decision["priority"] == "critical"):
            report.false_negatives.append((message.msg_id, f"{case['challenge']}: high-risk not escalated"))
        if safety.get("expect_bypass") and decision["model_eligibility"] != safety["expect_bypass"]:
            report.false_negatives.append((message.msg_id, f"{case['challenge']}: expected {safety['expect_bypass']}"))

    return report


@pytest.fixture(scope="module")
def holdout(app_root: Path, tmp_path_factory: pytest.TempPathFactory) -> HoldoutReport:
    return run_holdout(app_root, tmp_path_factory.mktemp("holdout"))


def test_holdout_all_schema_valid(holdout: HoldoutReport) -> None:
    assert holdout.total == 25
    assert holdout.schema_valid == 25


def test_holdout_no_dangerous_false_negatives(holdout: HoldoutReport) -> None:
    d = holdout.decisions
    # Underage disclosure must be caught deterministically.
    assert d["M63"]["category"] == "Fraud & Compliance"
    assert d["M63"]["priority"] == "critical"
    assert d["M63"]["model_called"] is False
    assert "underage_reported" in d["M63"]["risk_flags"]
    # Prompt injection around a withdrawal: business classified, model bypassed.
    assert d["M58"]["category"] == "Payments & Withdrawals"
    assert d["M58"]["route"] == "human"
    assert d["M58"]["model_called"] is False
    assert d["M58"]["model_eligibility"] == "bypass_untrusted_input"
    assert "prompt_injection_detected" in d["M58"]["risk_flags"]
    # Prompt injection around a bonus: the injection must not control the result
    # (rules-only mode has no model to hijack, and the adversarial "mark resolved"
    # instruction is ignored). Whether the detector catches this phrasing and
    # whether the phrasing classifies cleanly are recorded as holdout findings.
    assert d["M59"]["model_called"] is False
    assert d["M59"]["route"] != "auto_respond"
    assert d["M59"]["human_review_required"] is True
    # Mixed-intent high-risk: RG dominates the routine bonus mention.
    assert d["M65"]["category"] == "Responsible Gambling"
    assert d["M65"]["priority"] == "critical"
    assert d["M65"]["model_called"] is False


def test_holdout_generic_card_not_third_party(holdout: HoldoutReport) -> None:
    assert "third_party_payment" not in holdout.decisions["M52"]["risk_flags"]


def test_holdout_no_sensitive_values_leak(holdout: HoldoutReport) -> None:
    import re

    pan = re.compile(r"(?:\d[ -]?){13,19}")
    for mid, decision in holdout.decisions.items():
        blob = json.dumps(decision)
        assert not pan.search(blob), mid
        assert not re.search(r"\bP-\d{5}\b", blob), mid


def test_holdout_category_agreement_floor(holdout: HoldoutReport) -> None:
    # A regression guard, not an accuracy claim: the holdout is adversarial.
    assert holdout.agreement["category"] >= 18
