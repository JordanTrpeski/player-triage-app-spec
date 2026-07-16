"""Independent holdout-v2 evaluation (Phase 03D).

Reported separately from the supplied-40, holdout-v1 and the regression fixtures.
Expected results in ``tests/data/holdout_v2.json`` were written before running the
engine. Enforces the Phase 03D acceptance gates: zero sensitive-secret false
negatives, zero prompt-injection cases on a model-eligible path, complete explicit
self-exclusion recall, and no negated/informational/quoted case classified as an
explicit request (harm cases still escalate).
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


@dataclass
class Report:
    total: int = 0
    schema_valid: int = 0
    agreement: dict[str, int] = field(default_factory=lambda: {f: 0 for f in _FIELDS})
    mismatches: list[tuple[str, str, str, str]] = field(default_factory=list)
    decisions: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    cases: dict[str, dict[str, Any]] = field(default_factory=dict)


def _run(app_root: Path, tmp: Path) -> Report:
    data = json.loads((app_root / "tests" / "data" / "holdout_v2.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    csv_path = tmp / "holdout_v2.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        for c in cases:
            writer.writerow({k: c[k] for k in _COLUMNS})

    config = load_app_config(app_root)
    engine = TriageEngine.from_config(config)
    report = Report()
    report.cases = {c["msg_id"]: c for c in cases}
    for message in run_ingest(config, input_path=csv_path):
        result = engine.classify(message)
        d = result.decision
        report.decisions[message.msg_id] = d
        report.total += 1
        if result.schema_valid:
            report.schema_valid += 1
        exp = report.cases[message.msg_id]["expected"]
        for f in _FIELDS:
            if d.get(f) == exp.get(f):
                report.agreement[f] += 1
            else:
                report.mismatches.append((message.msg_id, f, str(exp.get(f)), str(d.get(f))))
    return report


@pytest.fixture(scope="module")
def report(app_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Report:
    return _run(app_root, tmp_path_factory.mktemp("holdout_v2"))


def test_v2_all_schema_valid(report: Report) -> None:
    assert report.total == 18
    assert report.schema_valid == 18


def test_v2_zero_secret_false_negatives(report: Report) -> None:
    for mid, case in report.cases.items():
        if case["safety"].get("secret_case"):
            d = report.decisions[mid]
            assert d["model_eligibility"] == "bypass_sensitive", mid
            assert d["model_called"] is False, mid
            assert d["priority"] == "critical", mid


def test_v2_zero_injection_model_eligible(report: Report) -> None:
    for mid, case in report.cases.items():
        if case["safety"].get("injection_case"):
            d = report.decisions[mid]
            assert d["model_eligibility"] == "bypass_untrusted_input", mid
            assert d["model_called"] is False, mid
            assert "prompt_injection_detected" in d["risk_flags"], mid


def test_v2_explicit_self_exclusion_recall_complete(report: Report) -> None:
    for mid, case in report.cases.items():
        if case["safety"].get("must_be_explicit_se"):
            d = report.decisions[mid]
            assert d["intent"] == "explicit_permanent_self_exclusion", mid
            assert d["category"] == "Responsible Gambling", mid
            assert d["priority"] == "critical", mid
            assert d["model_called"] is False, mid


def test_v2_negated_informational_quoted_not_explicit(report: Report) -> None:
    for mid, case in report.cases.items():
        if case["safety"].get("must_not_be_explicit_se"):
            d = report.decisions[mid]
            assert d["intent"] != "explicit_permanent_self_exclusion", mid


def test_v2_harm_cases_still_escalate(report: Report) -> None:
    for mid, case in report.cases.items():
        if case["safety"].get("expect_rg_critical"):
            d = report.decisions[mid]
            assert d["category"] == "Responsible Gambling", mid
            assert d["priority"] == "critical", mid


def test_v2_benign_not_injection(report: Report) -> None:
    for mid, case in report.cases.items():
        if case["safety"].get("must_not_be_injection"):
            assert report.decisions[mid]["model_eligibility"] != "bypass_untrusted_input", mid


def test_v2_otp_delivery_not_secret_bypass(report: Report) -> None:
    for mid, case in report.cases.items():
        if case["safety"].get("secret_must_not_bypass"):
            assert report.decisions[mid]["model_eligibility"] != "bypass_sensitive", mid


def test_v2_no_sensitive_values_leak(report: Report) -> None:
    import re

    pan = re.compile(r"(?:\d[ -]?){13,19}")
    for mid, d in report.decisions.items():
        blob = json.dumps(d)
        assert not pan.search(blob), mid
        assert not re.search(r"\bP-\d{5}\b", blob), mid
