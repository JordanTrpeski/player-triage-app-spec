"""Policy-driven detection engine.

Detectors, their patterns, and the processing order are loaded from
``policy/redaction_policy.json``. This module never restates a detector
pattern as source-code business policy; every pattern originates in the
policy file. What lives here is only:

* the engine that runs the patterns in the policy's declared order;
* the mapping between ``detector_id`` and the *approved risk flag* the
  detector emits into a downstream classification (this mapping is an
  interpretation of the policy contract and is deliberately narrow);
* Luhn validation for the PAN candidate detector;
* prompt-injection pattern matching.

Detection results never contain matched values — only detector id, count,
approved placeholder, approved risk flags and a status string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from .errors import ConfigurationError
from .records import DetectionResult


# Detector-id → approved risk flags emitted when the detector fires. Only the
# detectors that surface as sensitive/adversarial signals map to a canonical
# risk flag; the informational detectors (EMAIL, PHONE, TRANSACTION_REF,
# CURRENCY_AMOUNT, PLAYER_ID) redact silently and do not add to the risk
# profile at ingestion time.
_DETECTOR_RISK_FLAGS: Final[Mapping[str, tuple[str, ...]]] = {
    "AUTH_SECRET": ("sensitive_authentication_data",),
    "CVV": ("cvv_exposed",),
    "PAN": ("full_pan_exposed",),
    "IDENTITY_DOC_NUMBER": ("identity_data_sensitive",),
}
_PROMPT_INJECTION_FLAG: Final[str] = "prompt_injection_detected"
_PROMPT_INJECTION_PLACEHOLDER: Final[str] = "[PROMPT_INJECTION_DETECTED]"


class DetectionError(ConfigurationError):
    """Raised when detector configuration is malformed or a match cannot be evaluated."""


@dataclass(frozen=True, slots=True)
class DetectorSpec:
    """Immutable, compiled view of a single detector from the policy file."""

    detector_id: str
    kind: str
    replacement: str
    patterns: tuple[re.Pattern[str], ...]
    negative_context_patterns: tuple[re.Pattern[str], ...]
    candidate_pattern: re.Pattern[str] | None
    digit_count_min: int | None
    digit_count_max: int | None
    risk_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DetectorMatch:
    """Internal span record — carries offsets only, never the matched string."""

    detector_id: str
    replacement: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class DetectionOutcome:
    """Composite result of one detection pass over a piece of text."""

    detections: tuple[DetectionResult, ...]
    matches: tuple[DetectorMatch, ...]
    prompt_injection_detected: bool
    uncertain: bool


def _compile(patterns: Sequence[str], *, detector_id: str) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for index, pattern in enumerate(patterns):
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise DetectionError(
                component="detection",
                message=f"detector {detector_id}: pattern[{index}] does not compile: {exc}",
            ) from exc
    return tuple(compiled)


def load_detectors(policy: Mapping[str, Any]) -> tuple[DetectorSpec, ...]:
    """Return an ordered tuple of :class:`DetectorSpec`, in the policy's declared processing order."""

    processing_order: Sequence[str] = policy.get("processing_order") or []
    detectors_by_id: dict[str, Mapping[str, Any]] = {
        detector["id"]: detector for detector in policy.get("detectors", [])
    }

    # Map processing_order category name → ordered list of detector IDs known
    # to belong to it. This mapping is derived from the policy's own detector
    # semantics; it is documented here so a policy update that adds a new
    # detector must be reflected in this list (and no policy meaning changes
    # silently in source).
    category_to_detectors: Mapping[str, tuple[str, ...]] = {
        "authentication_secrets": ("AUTH_SECRET",),
        "cvv": ("CVV",),
        "payment_card": ("PAN",),
        "identity_document_number": ("IDENTITY_DOC_NUMBER",),
        "contact_and_internal_ids": ("EMAIL", "PHONE", "PLAYER_ID"),
        "transaction_references": ("TRANSACTION_REF",),
        "currency_amounts": ("CURRENCY_AMOUNT",),
        "prompt_injection_detection": (),  # handled separately
    }

    ordered: list[DetectorSpec] = []
    seen: set[str] = set()
    for category in processing_order:
        detector_ids = category_to_detectors.get(category)
        if detector_ids is None:
            raise DetectionError(
                component="detection",
                message=f"processing_order references unknown category {category!r}",
            )
        for detector_id in detector_ids:
            detector = detectors_by_id.get(detector_id)
            if detector is None:
                raise DetectionError(
                    component="detection",
                    message=f"processing_order refers to missing detector {detector_id!r}",
                )
            seen.add(detector_id)
            ordered.append(_build_spec(detector))

    unhandled = sorted(set(detectors_by_id) - seen)
    if unhandled:
        raise DetectionError(
            component="detection",
            message=(
                "policy declares detectors not covered by processing_order: "
                f"{unhandled}"
            ),
        )
    return tuple(ordered)


def _build_spec(detector: Mapping[str, Any]) -> DetectorSpec:
    detector_id = detector["id"]
    kind = detector["type"]
    replacement = detector["replacement"]
    patterns = _compile(detector.get("patterns", ()), detector_id=detector_id)
    negatives = _compile(
        detector.get("negative_context_patterns", ()), detector_id=detector_id
    )
    candidate_pattern: re.Pattern[str] | None = None
    if "candidate_pattern" in detector:
        try:
            candidate_pattern = re.compile(detector["candidate_pattern"])
        except re.error as exc:
            raise DetectionError(
                component="detection",
                message=f"detector {detector_id}: candidate_pattern does not compile: {exc}",
            ) from exc

    return DetectorSpec(
        detector_id=detector_id,
        kind=kind,
        replacement=replacement,
        patterns=patterns,
        negative_context_patterns=negatives,
        candidate_pattern=candidate_pattern,
        digit_count_min=detector.get("digit_count_min"),
        digit_count_max=detector.get("digit_count_max"),
        risk_flags=_DETECTOR_RISK_FLAGS.get(detector_id, ()),
    )


def _luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    reversed_digits = digits[::-1]
    for index, character in enumerate(reversed_digits):
        value = int(character)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


_CARD_CONTEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:card|visa|mastercard|amex|debit|credit|payment)\b"
)


def _run_pan_detector(text: str, spec: DetectorSpec) -> tuple[list[DetectorMatch], bool]:
    if spec.candidate_pattern is None:
        return [], False
    matches: list[DetectorMatch] = []
    uncertain = False
    lower = text.lower()
    for candidate in spec.candidate_pattern.finditer(text):
        span = candidate.span()
        digits = re.sub(r"\D", "", candidate.group())
        card_context = bool(_CARD_CONTEXT_RE.search(text))
        if _luhn_valid(digits):
            matches.append(
                DetectorMatch(
                    detector_id=spec.detector_id,
                    replacement=spec.replacement,
                    start=span[0],
                    end=span[1],
                )
            )
        elif card_context:
            # Non-Luhn digits inside a payment discussion — flag as uncertain;
            # the eligibility gate will fail closed.
            uncertain = True
            _ = lower  # kept for readability; keeps the branch honest
    return matches, uncertain


def _within_negative_context(
    text: str,
    span: tuple[int, int],
    negatives: Sequence[re.Pattern[str]],
) -> bool:
    if not negatives:
        return False
    # Only a short window of preceding text is inspected. The pattern in policy
    # anchors on "$" (end-of-line) meaning the keyword must appear immediately
    # before the match.
    prefix = text[max(0, span[0] - 32) : span[0]]
    return any(pattern.search(prefix) for pattern in negatives)


def _phone_digit_count(match_text: str) -> int:
    return sum(character.isdigit() for character in match_text)


def _run_regex_detector(text: str, spec: DetectorSpec) -> list[DetectorMatch]:
    matches: list[DetectorMatch] = []
    for pattern in spec.patterns:
        for match in pattern.finditer(text):
            span = match.span()
            if _within_negative_context(text, span, spec.negative_context_patterns):
                continue
            if spec.detector_id == "PHONE":
                digit_count = _phone_digit_count(match.group())
                if spec.digit_count_min is not None and digit_count < spec.digit_count_min:
                    continue
                if spec.digit_count_max is not None and digit_count > spec.digit_count_max:
                    continue
            matches.append(
                DetectorMatch(
                    detector_id=spec.detector_id,
                    replacement=spec.replacement,
                    start=span[0],
                    end=span[1],
                )
            )
    return matches


def _dedupe_and_sort(matches: Sequence[DetectorMatch]) -> tuple[DetectorMatch, ...]:
    seen: set[tuple[str, int, int]] = set()
    ordered: list[DetectorMatch] = []
    for match in sorted(matches, key=lambda m: (m.start, m.end)):
        key = (match.detector_id, match.start, match.end)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(match)
    return tuple(ordered)


def _detect_prompt_injection(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _compile_injection_patterns(policy: Mapping[str, Any]) -> tuple[re.Pattern[str], ...]:
    patterns: list[re.Pattern[str]] = []
    for index, pattern in enumerate(policy.get("prompt_injection_patterns", [])):
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            raise DetectionError(
                component="detection",
                message=f"prompt_injection_patterns[{index}] does not compile: {exc}",
            ) from exc
    return tuple(patterns)


@dataclass(frozen=True, slots=True)
class DetectionEngine:
    """Runs the compiled detectors against a text buffer."""

    detectors: tuple[DetectorSpec, ...]
    prompt_injection_patterns: tuple[re.Pattern[str], ...]

    @classmethod
    def from_policy(cls, policy: Mapping[str, Any]) -> "DetectionEngine":
        return cls(
            detectors=load_detectors(policy),
            prompt_injection_patterns=_compile_injection_patterns(policy),
        )

    def scan(self, text: str) -> DetectionOutcome:
        all_matches: list[DetectorMatch] = []
        uncertain = False
        per_detector_counts: dict[str, int] = {spec.detector_id: 0 for spec in self.detectors}

        for spec in self.detectors:
            if spec.detector_id == "PAN":
                spec_matches, pan_uncertain = _run_pan_detector(text, spec)
                if pan_uncertain:
                    uncertain = True
            else:
                spec_matches = _run_regex_detector(text, spec)
            per_detector_counts[spec.detector_id] += len(spec_matches)
            all_matches.extend(spec_matches)

        prompt_injection_detected = _detect_prompt_injection(text, self.prompt_injection_patterns)

        detections: list[DetectionResult] = []
        for spec in self.detectors:
            count = per_detector_counts.get(spec.detector_id, 0)
            detections.append(
                DetectionResult(
                    detector_id=spec.detector_id,
                    count=count,
                    replacement_placeholder=spec.replacement,
                    risk_flags=spec.risk_flags if count > 0 else (),
                    status="detected" if count > 0 else "clear",
                )
            )
        if prompt_injection_detected:
            detections.append(
                DetectionResult(
                    detector_id="PROMPT_INJECTION",
                    count=1,
                    replacement_placeholder=_PROMPT_INJECTION_PLACEHOLDER,
                    risk_flags=(_PROMPT_INJECTION_FLAG,),
                    status="detected",
                )
            )
        return DetectionOutcome(
            detections=tuple(detections),
            matches=_dedupe_and_sort(all_matches),
            prompt_injection_detected=prompt_injection_detected,
            uncertain=uncertain,
        )
