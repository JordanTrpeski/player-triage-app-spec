"""Phase 02 ingestion pipeline.

Turns the authoritative input file into a sequence of :class:`IngestedMessage`
records. Semantic classification is *not* performed here — that begins in
Phase 03. The public output of this pipeline carries no ``player_id`` and no
raw subject/body text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .config import AppConfig
from .detection import DetectionEngine
from .eligibility import decide as decide_eligibility
from .ingestion import load as load_raw
from .linkage import build_linkage
from .normalization import normalize_message
from .overlays import MarketOverlay, load_overlays
from .records import IngestedMessage, LinkageResult, RawMessage
from .redaction import apply_redaction, detect_reference_flags


def _default_input(config: AppConfig) -> Path:
    return config.app_root / "input" / "dataset_player_messages.csv"


def ingest(
    config: AppConfig,
    input_path: Path | str | None = None,
) -> tuple[IngestedMessage, ...]:
    """Run the full Phase 02 pipeline over the requested input file."""

    source = Path(input_path) if input_path is not None else _default_input(config)
    raw_messages = load_raw(source)
    engine = DetectionEngine.from_policy(config.component("redaction_policy"))
    overlays = load_overlays(config.component("market_overlays"))
    linkage_map = build_linkage(raw_messages)

    ingested: list[IngestedMessage] = []
    for raw in raw_messages:
        ingested.append(_process_one(raw, engine, overlays, linkage_map[raw.msg_id]))
    return tuple(ingested)


def _process_one(
    raw: RawMessage,
    engine: DetectionEngine,
    overlays: Mapping[str, MarketOverlay],
    linkage: LinkageResult,
) -> IngestedMessage:
    normalized = normalize_message(raw)
    combined_for_detection = f"{normalized.normalized_subject}\n{normalized.normalized_body}"
    outcome = engine.scan(combined_for_detection)
    redacted_text = apply_redaction(combined_for_detection, outcome)
    reference_flags = detect_reference_flags(combined_for_detection, outcome)

    eligibility = decide_eligibility(
        normalized=normalized,
        detections=outcome.detections,
        prompt_injection_detected=outcome.prompt_injection_detected,
        redaction_uncertain=outcome.uncertain,
        reference_flags=reference_flags,
        attachment_received=False,  # dataset never carries actual attachment metadata
    )

    overlay = overlays.get(normalized.market)
    if overlay is None:
        market_codes: tuple[str, ...] = ()
        framework_status = ""
    else:
        market_codes = overlay.codes
        framework_status = overlay.status

    return IngestedMessage(
        msg_id=normalized.msg_id,
        received_utc=normalized.received_utc,
        channel=normalized.channel,
        market=normalized.market,
        language=normalized.language,
        normalization_version=normalized.normalization_version,
        redacted_text=redacted_text,
        detections=outcome.detections,
        eligibility=eligibility,
        linkage=linkage,
        market_overlay_codes=market_codes,
        market_framework_status=framework_status,
    )
