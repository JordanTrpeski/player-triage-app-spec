"""The Phase 03 routing map must not drift from the controlled vocabulary.

``phase03_routing.json`` holds relational maps and structural constants as data
(so no classification-catalogue literal appears in ``*.py``). This test is the
drift guard that justifies that: every value it references must be a member of
the authoritative ``policy/controlled_vocabularies.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from player_triage.routing import load_routing_map


@pytest.fixture(scope="module")
def vocab(app_root: Path) -> dict[str, set[str]]:
    raw = json.loads(
        (app_root / "policy" / "controlled_vocabularies.json").read_text(encoding="utf-8")
    )
    return {name: set(values) for name, values in raw.items() if isinstance(values, list)}


def test_constants_are_valid_vocabulary(vocab: dict[str, set[str]]) -> None:
    const = load_routing_map().constants
    assert const.auto_respond in vocab["routes"]
    assert const.human in vocab["routes"]
    assert const.specialist in vocab["routes"]
    assert const.allowed_template in vocab["auto_response_policies"]
    assert const.acknowledgment_only in vocab["auto_response_policies"]
    assert const.requires_approval in vocab["auto_response_policies"]
    assert const.prohibited in vocab["auto_response_policies"]
    assert const.eligible in vocab["model_eligibility"]
    assert const.general_category in vocab["categories"]
    assert const.unclassified_intent in vocab["intents"]
    assert const.general_support_team in vocab["teams"]
    assert const.market_compliance_team in vocab["teams"]
    assert const.india_overlay_reason in vocab["reason_codes"]
    assert const.prohibited_market_status in vocab["market_framework_status"]
    assert const.claimed_missing_win_flag in vocab["intents"]


def test_category_default_team_valid(vocab: dict[str, set[str]]) -> None:
    routing = load_routing_map()
    for category, team in routing.category_default_team.items():
        assert category in vocab["categories"], category
        assert team in vocab["teams"], team


def test_static_template_intents_valid(vocab: dict[str, set[str]]) -> None:
    routing = load_routing_map()
    for intent, (template_id, reason_code) in routing.static_template_intents.items():
        assert intent in vocab["intents"], intent
        assert template_id in vocab["auto_response_template_ids"], template_id
        assert reason_code in vocab["reason_codes"], reason_code


def test_intent_reason_code_valid(vocab: dict[str, set[str]]) -> None:
    routing = load_routing_map()
    for intent, reason_code in routing.intent_reason_code.items():
        assert intent in vocab["intents"], intent
        assert reason_code in vocab["reason_codes"], reason_code
