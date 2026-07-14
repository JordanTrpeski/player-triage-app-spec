"""Market overlay lookup driven by ``policy/market_overlays.json``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class MarketOverlay:
    market: str
    status: str
    codes: tuple[str, ...]
    routing_effect: str


def load_overlays(policy: Mapping[str, Any]) -> Mapping[str, MarketOverlay]:
    overlays_raw = policy.get("overlays")
    if not isinstance(overlays_raw, list):
        raise ConfigurationError(
            component="market_overlays",
            message="policy is missing an 'overlays' list",
        )
    result: dict[str, MarketOverlay] = {}
    for index, entry in enumerate(overlays_raw):
        if not isinstance(entry, dict):
            raise ConfigurationError(
                component="market_overlays",
                message=f"overlay[{index}] is not an object",
            )
        market = entry.get("market")
        if not isinstance(market, str):
            raise ConfigurationError(
                component="market_overlays",
                message=f"overlay[{index}].market is missing or not a string",
            )
        result[market] = MarketOverlay(
            market=market,
            status=entry.get("status", ""),
            codes=tuple(entry.get("codes", ())),
            routing_effect=entry.get("routing_effect", ""),
        )
    return result
