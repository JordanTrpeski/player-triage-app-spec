"""Typed model invocation, aggregation, trace and audit orchestration.

This keeps optional-model concerns out of the deterministic engine. Providers
own runtime/retry mechanics; the validator owns schema/policy validation; this
module coordinates only sanitized semantic candidates and deterministic policy
state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..baseline_classifier import BaselineOutcome
from ..records import IngestedMessage
from ..routing import RoutingConstants
from ..signals import SignalContext
from ..working import WorkingDecision
from .contract import ModelCandidate, ModelResult, SemanticClassifier
from .gate import ModelCallGate


@dataclass(frozen=True, slots=True)
class ModelInvocationOutcome:
    gate_reason: str
    result: ModelResult | None
    candidate: ModelCandidate | None
    agreement: bool | None


@dataclass(frozen=True, slots=True)
class ModelDecisionTrace:
    mode: str
    gate_reason: str
    provider: str
    called: bool
    rules_candidate: Mapping[str, object]
    model_candidate: Mapping[str, object] | None
    agreement: bool | None
    deterministic_overrides: tuple[str, ...]
    error: str | None
    fallback_reason: str | None
    latency_ms: float
    retries: int


@dataclass(frozen=True, slots=True)
class ModelInvocationCoordinator:
    gate: ModelCallGate
    provider: SemanticClassifier
    categories: tuple[str, ...]
    intents: tuple[str, ...]

    def invoke(
        self,
        message: IngestedMessage,
        ctx: SignalContext,
        decision: WorkingDecision,
        baseline: BaselineOutcome,
    ) -> ModelInvocationOutcome:
        gate_outcome = self.gate.evaluate(message, ctx, decision)
        if not gate_outcome.allowed:
            return ModelInvocationOutcome(gate_outcome.reason, None, None, None)
        request = self.gate.build_request(
            message, categories=self.categories, intents=self.intents
        )
        try:
            result = self.provider.classify(request)
        except Exception:
            result = ModelResult(
                provider=self.provider.name,
                called=True,
                error="MODEL_RUNTIME_FAILURE",
                fallback_reason="MODEL_UNAVAILABLE",
            )
        candidate = result.candidate if result.valid else None
        agreement = None
        if candidate is not None:
            agreement = (
                baseline.category == candidate.category and baseline.intent == candidate.intent
            )
        return ModelInvocationOutcome(gate_outcome.reason, result, candidate, agreement)


@dataclass(frozen=True, slots=True)
class ModelCandidateAggregator:
    const: RoutingConstants

    def apply(
        self,
        decision: WorkingDecision,
        baseline: BaselineOutcome,
        candidate: ModelCandidate,
    ) -> None:
        if baseline.intent is not None and baseline.intent != candidate.intent:
            decision.add_values("secondary_intents", [baseline.intent], stage="aggregation")
        decision.set_scalar("category", candidate.category, stage="model_semantic")
        decision.set_scalar("intent", candidate.intent, stage="model_semantic")
        decision.add_values(
            "secondary_intents", list(candidate.secondary_intents), stage="model_semantic"
        )
        decision.add_values("risk_flags", list(candidate.signals), stage="model_semantic")
        decision.decision_basis = "model_assisted"

    def mark_fallback(self, decision: WorkingDecision, reason: str) -> None:
        decision.add_values("risk_flags", ["classification_uncertain"], stage="manual_fallback")
        if reason in {"MODEL_UNAVAILABLE", "MODEL_TIMEOUT"}:
            decision.add_values("risk_flags", ["model_unavailable"], stage="manual_fallback")
            decision.add_values("reason_codes", ["MODEL_UNAVAILABLE"], stage="manual_fallback")
        elif reason == "MODEL_SCHEMA_INVALID":
            decision.add_values("risk_flags", ["schema_failure"], stage="manual_fallback")
            decision.add_values("reason_codes", ["MODEL_SCHEMA_INVALID"], stage="manual_fallback")
        else:
            decision.add_values(
                "reason_codes", ["UNCLASSIFIED_MANUAL_REVIEW"], stage="manual_fallback"
            )
        decision.set_scalar("route", self.const.human, stage="manual_fallback", force=True)
        decision.set_scalar(
            "auto_response_policy",
            self.const.acknowledgment_only,
            stage="manual_fallback",
            force=True,
        )
        decision.set_scalar("auto_response_template_id", None, stage="manual_fallback", force=True)
        decision.set_scalar("human_review_required", True, stage="manual_fallback", force=True)
        decision.decision_basis = "manual_fallback"


class ModelTraceBuilder:
    @staticmethod
    def rules_candidate(baseline: BaselineOutcome) -> Mapping[str, object]:
        return {
            "category": baseline.category,
            "intent": baseline.intent,
            "secondary_intents": tuple(baseline.secondary_intents),
            "risk_flags": tuple(baseline.risk_flags),
        }

    @staticmethod
    def build(
        *,
        mode: str,
        provider_name: str,
        rules_candidate: Mapping[str, object],
        invocation: ModelInvocationOutcome,
        final_decision: Mapping[str, object],
    ) -> ModelDecisionTrace:
        result = invocation.result
        candidate = invocation.candidate
        overrides: list[str] = []
        if candidate is not None:
            if final_decision.get("category") != candidate.category:
                overrides.append("category")
            if final_decision.get("intent") != candidate.intent:
                overrides.append("intent")
            raw_secondary = final_decision.get("secondary_intents", ())
            final_secondary = set(
                raw_secondary if isinstance(raw_secondary, (list, tuple, set)) else ()
            )
            if not set(candidate.secondary_intents).issubset(final_secondary):
                overrides.append("secondary_intents")
            raw_flags = final_decision.get("risk_flags", ())
            final_flags = set(raw_flags if isinstance(raw_flags, (list, tuple, set)) else ())
            if not set(candidate.signals).issubset(final_flags):
                overrides.append("signals")
        return ModelDecisionTrace(
            mode=mode,
            gate_reason=invocation.gate_reason,
            provider=result.provider if result else provider_name,
            called=bool(result and result.called),
            rules_candidate=rules_candidate,
            model_candidate=candidate.as_dict() if candidate else None,
            agreement=invocation.agreement,
            deterministic_overrides=tuple(overrides),
            error=result.error if result else None,
            fallback_reason=(
                normalise_fallback(result)
                if result is not None and candidate is None
                else (
                    "NO_CLASSIFICATION_CANDIDATE"
                    if candidate is not None and candidate.ambiguity != "clear"
                    else None
                )
            ),
            latency_ms=result.latency_ms if result else 0.0,
            retries=result.retries if result else 0,
        )


class ModelAuditBuilder:
    @staticmethod
    def failure_event(
        decision: Mapping[str, Any],
        trace: ModelDecisionTrace,
        *,
        bundle_version: str,
        run_id: str,
    ) -> dict[str, Any] | None:
        reason = trace.fallback_reason
        if reason not in {
            "MODEL_UNAVAILABLE",
            "MODEL_TIMEOUT",
            "MODEL_SCHEMA_INVALID",
            "NO_CLASSIFICATION_CANDIDATE",
        }:
            return None
        return {
            "audit_schema_version": "3.0",
            "event_id": f"model-fallback-{decision['message_id']}",
            "event_type": "error_fallback",
            "run_id": run_id,
            "occurred_at": str(decision["received_utc"]),
            "message_id": decision["message_id"],
            "actor": {"type": "system", "role": "classifier-service", "actor_ref": None},
            "configuration_version": bundle_version,
            "payload": {
                "stage": "model",
                "reason_code": reason,
                "fallback_route": decision["route"],
                "sanitized_error": trace.error,
            },
        }


def normalise_fallback(result: ModelResult) -> str:
    if result.fallback_reason in {
        "MODEL_UNAVAILABLE",
        "MODEL_TIMEOUT",
        "MODEL_SCHEMA_INVALID",
        "NO_CLASSIFICATION_CANDIDATE",
    }:
        return str(result.fallback_reason)
    return "MODEL_UNAVAILABLE"
