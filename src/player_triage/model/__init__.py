"""Optional local-model semantic-classifier adapter (Phase 04).

The model is NOT the decision authority. It may only propose category / intent /
secondary intents / signals / complaint indicator / ambiguity for already-approved,
redacted, model-eligible text. The deterministic policy engine remains
authoritative for eligibility, safety, priority, route, team, human review,
auto-response and market overlays.

Runtime-specific code (llama.cpp) lives only in
:mod:`player_triage.model.providers` behind a lazy import, so ``rules_only`` mode
never imports or initialises the model runtime.
"""

from __future__ import annotations

from .contract import ModelCandidate, ModelClassificationRequest, ModelResult, SemanticClassifier
from .configuration import build_local_classifier, resolve_model_path
from .gate import ModelCallGate, ModelGateOutcome
from .providers import (
    DeterministicFakeSemanticClassifier,
    DisabledSemanticClassifier,
    LocalModelSemanticClassifier,
    LocalModelSettings,
    RulesOnlySemanticClassifier,
)
from .validate import (
    CandidateJSONDecodeError,
    CandidatePolicyRejection,
    CandidateSchemaError,
    CandidateValidator,
)

__all__ = [
    "CandidateJSONDecodeError",
    "CandidatePolicyRejection",
    "CandidateSchemaError",
    "CandidateValidator",
    "build_local_classifier",
    "DeterministicFakeSemanticClassifier",
    "DisabledSemanticClassifier",
    "LocalModelSemanticClassifier",
    "LocalModelSettings",
    "ModelCallGate",
    "ModelCandidate",
    "ModelClassificationRequest",
    "ModelResult",
    "ModelGateOutcome",
    "RulesOnlySemanticClassifier",
    "resolve_model_path",
    "SemanticClassifier",
]
