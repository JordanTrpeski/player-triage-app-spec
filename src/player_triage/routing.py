"""Loader for the Phase 03 routing map (``phase03_routing.json``).

The classification-catalogue single-source rule forbids restating category /
intent / route / team / template values as Python string literals. The Phase 03
engine nonetheless needs a few relational maps (category -> default team,
intent -> static template, intent -> reason code) and a handful of structural
constants (the ``auto_respond`` route, the ``allowed_template`` policy, ...).

Those live as *data* in ``phase03_routing.json`` and are loaded here, so no
forbidden literal appears in source. ``tests/test_phase03_no_vocab_drift.py``
asserts every value is a member of the authoritative controlled vocabulary, so
the map cannot silently drift from policy.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

_DATA_FILE = Path(__file__).with_name("phase03_routing.json")


@dataclass(frozen=True, slots=True)
class RoutingConstants:
    auto_respond: str
    human: str
    specialist: str
    allowed_template: str
    acknowledgment_only: str
    requires_approval: str
    prohibited: str
    eligible: str
    general_category: str
    unclassified_intent: str
    general_support_team: str
    market_compliance_team: str
    india_overlay_reason: str
    prohibited_market_status: str
    claimed_missing_win_flag: str


@dataclass(frozen=True, slots=True)
class RoutingMap:
    constants: RoutingConstants
    category_default_team: Mapping[str, str]
    static_template_intents: Mapping[str, tuple[str, str]]
    intent_reason_code: Mapping[str, str]


@functools.lru_cache(maxsize=1)
def load_routing_map() -> RoutingMap:
    raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    static = {
        intent: (entry["template_id"], entry["reason_code"])
        for intent, entry in raw["static_template_intents"].items()
    }
    return RoutingMap(
        constants=RoutingConstants(**raw["constants"]),
        category_default_team=MappingProxyType(dict(raw["category_default_team"])),
        static_template_intents=MappingProxyType(static),
        intent_reason_code=MappingProxyType(dict(raw["intent_reason_code"])),
    )
