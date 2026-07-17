"""Phase 03 rules-only classification orchestrator.

Runs the eight typed stages in order and returns a schema-valid decision plus
its provenance trace:

a. pre-model deterministic safety evaluation
b. rules-only semantic candidate generation
c. candidate aggregation and precedence
d. deterministic final-policy application
e. market overlay
f. approved rationale rendering
g. JSON Schema validation
h. semantic cross-field validation

If classification cannot produce a safe, valid result the engine fails closed to
a manual fallback that is still schema- and semantic-valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from .baseline_classifier import BaselineClassifier, BaselineOutcome
from .config import DERIVED_REFINEMENT_COMPONENT, AppConfig
from .decision import assemble_decision, manual_fallback_decision
from .derived_rules import DerivedRuleEngine
from .final_policy import FinalPolicy
from .model import (
    DisabledSemanticClassifier,
    ModelCallGate,
    RulesOnlySemanticClassifier,
    SemanticClassifier,
)
from .model.orchestration import (
    ModelAuditBuilder,
    ModelCandidateAggregator,
    ModelDecisionTrace,
    ModelInvocationCoordinator,
    ModelTraceBuilder,
    normalise_fallback,
)
from .records import IngestedMessage
from .rule_engine import RuleEngine
from .signals import SignalContext, build_signals
from .validation import SemanticValidator, Violation
from .working import TraceEntry, WorkingDecision

_OUTPUT_SCHEMA_FILE = "output_schema.json"


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    decision: dict[str, Any]
    trace: tuple[TraceEntry, ...]
    matched_pre_model: tuple[str, ...]
    matched_post_semantic: tuple[str, ...]
    matched_derived: tuple[str, ...]
    baseline_rule_ids: tuple[str, ...]
    refinement_ids: tuple[str, ...]
    schema_valid: bool
    semantic_violations: tuple[Violation, ...]
    model_trace: "ModelDecisionTrace"

    @property
    def message_id(self) -> str:
        return str(self.decision["message_id"])

    def decision_path(self) -> str:
        seen: list[str] = []
        for entry in self.trace:
            label = entry.rule_id or entry.stage
            if label not in seen:
                seen.append(label)
        return " > ".join(seen)


@dataclass(frozen=True, slots=True)
class TriageEngine:
    config: AppConfig
    rule_engine: RuleEngine
    classifier: BaselineClassifier
    derived_engine: DerivedRuleEngine
    final_policy: FinalPolicy
    semantic_validator: SemanticValidator
    semantic_classifier: SemanticClassifier
    model_gate: ModelCallGate
    model_invoker: ModelInvocationCoordinator
    model_aggregator: ModelCandidateAggregator

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        *,
        mode: str = "rules_only",
        semantic_classifier: SemanticClassifier | None = None,
        kill_switch: bool = False,
    ) -> "TriageEngine":
        if mode not in {"rules_only", "local_model"}:
            raise ValueError("mode must be rules_only or local_model")
        provider: SemanticClassifier
        if semantic_classifier is None:
            if mode == "rules_only":
                provider = cast(SemanticClassifier, RulesOnlySemanticClassifier())
            else:
                from .model.configuration import build_local_classifier

                provider = cast(SemanticClassifier, build_local_classifier(config))
        else:
            provider = semantic_classifier
        final_policy = FinalPolicy.from_config(
            config.component("auto_response_templates"),
            config.component("baseline_intent_rules"),
            config.component("rationale_templates"),
        )
        gate = ModelCallGate(mode=mode, kill_switch=kill_switch)
        return cls(
            config=config,
            rule_engine=RuleEngine.from_policy(config.component("policy_rules")),
            classifier=BaselineClassifier.from_policy(config.component("baseline_intent_rules")),
            derived_engine=(
                DerivedRuleEngine.from_component(config.component(DERIVED_REFINEMENT_COMPONENT))
                if config.has_component(DERIVED_REFINEMENT_COMPONENT)
                else DerivedRuleEngine.empty()
            ),
            final_policy=final_policy,
            semantic_validator=SemanticValidator.from_config(config),
            semantic_classifier=provider,
            model_gate=gate,
            model_invoker=ModelInvocationCoordinator(
                gate=gate,
                provider=provider,
                categories=tuple(config.vocab.categories),
                intents=tuple(config.vocab.intents),
            ),
            model_aggregator=ModelCandidateAggregator(final_policy.const),
        )

    # -- governance provenance ---------------------------------------------
    @property
    def bundle_version(self) -> str:
        return self.config.bundle_version

    @property
    def derived_component_version(self) -> str | None:
        if not self.config.has_component(DERIVED_REFINEMENT_COMPONENT):
            return None
        return self.derived_engine.version

    @property
    def derived_component_digest(self) -> str | None:
        return self.config.component_digest(DERIVED_REFINEMENT_COMPONENT)

    def close(self) -> None:
        """Release an optional isolated model worker; rules-only is a no-op."""

        close = getattr(self.semantic_classifier, "close", None)
        if callable(close):
            close()

    def build_decision_audit_event(
        self, result: ClassificationResult, *, run_id: str = "run", processing_time_ms: int = 1
    ) -> dict[str, Any]:
        """Build a schema-valid decision audit event carrying policy provenance.

        Records the policy bundle version, the derived-refinement component
        version and digest, and every rule id triggered (pre-model, post-semantic
        and derived). Nothing sensitive is included: only enum/id/flag values.
        """

        decision = result.decision
        risk_flags = list(decision.get("risk_flags", []))
        eligibility = decision.get("model_eligibility")
        rules_triggered = list(
            result.matched_pre_model + result.matched_post_semantic + result.matched_derived
        )
        return {
            "audit_schema_version": "3.0",
            "event_id": f"event-{decision['message_id']}",
            "event_type": "decision",
            "run_id": run_id,
            "occurred_at": str(decision["received_utc"]),
            "message_id": decision["message_id"],
            "actor": {"type": "system", "role": "classifier-service", "actor_ref": None},
            "configuration_version": self.bundle_version,
            "payload": {
                "input_metadata": {
                    "language": decision["language"],
                    "channel": decision["channel"],
                    "market": decision["market"],
                    "attachment_received": decision["attachment_received"],
                    "attachment_referenced": decision["attachment_referenced"],
                    "sensitive_data_types": list(decision.get("sensitive_data_types", [])),
                    "prompt_injection_detected": "prompt_injection_detected" in risk_flags,
                    "redaction_status": "blocked" if eligibility == "bypass_sensitive" else "passed",
                    "redaction_count": len(decision.get("sensitive_data_types", [])),
                },
                "decision_path": decision["decision_basis"],
                "rules_triggered": rules_triggered,
                "result": decision,
                "controls": {
                    "schema_valid": result.schema_valid,
                    "semantic_valid": not result.semantic_violations,
                    "policy_override_applied": bool(
                        result.matched_derived or result.model_trace.deterministic_overrides
                    ),
                    "fallback_reason": result.model_trace.fallback_reason,
                },
                "processing_time_ms": processing_time_ms,
                "component_provenance": {
                    "policy_bundle_version": self.bundle_version,
                    "derived_refinement_version": self.derived_component_version,
                    "derived_refinement_digest": self.derived_component_digest,
                    "derived_rules_triggered": list(result.matched_derived),
                },
            },
        }

    def build_model_failure_audit_event(
        self,
        result: ClassificationResult,
        *,
        run_id: str = "run",
    ) -> dict[str, Any] | None:
        """Return a schema-valid, metadata-only model fallback event if needed."""

        return ModelAuditBuilder.failure_event(
            result.decision,
            result.model_trace,
            bundle_version=self.bundle_version,
            run_id=run_id,
        )

    def classify(self, message: IngestedMessage) -> ClassificationResult:
        ctx = build_signals(message)
        decision = WorkingDecision(msg_id=message.msg_id)

        # Stage a — pre-model safety.
        matched_pre = self.rule_engine.evaluate_pre_model(decision, ctx)
        self._apply_ingestion_eligibility(decision, ctx)

        # Stage b — rules-only semantic candidate.
        baseline = self.classifier.classify(ctx)

        # Stage c — aggregation and precedence.
        self._aggregate(decision, baseline)

        # Deterministic post-semantic rules depend only on the rules candidate
        # and redacted context. Evaluate them before constructing any model
        # request so deterministic terminal outcomes are true no-call paths.
        matched_post = self.rule_engine.evaluate_post_semantic(decision, ctx)
        self._demote_overridden_intent(decision, baseline)
        self._add_reference_flags(decision, ctx)

        # Stage b' - optional model semantic candidate. The request cannot be
        # constructed unless every deterministic safety-gate condition passes.
        rules_candidate = ModelTraceBuilder.rules_candidate(baseline)
        invocation = self.model_invoker.invoke(message, ctx, decision, baseline)
        model_result = invocation.result
        model_candidate = invocation.candidate
        model_fallback_engaged = False
        if model_candidate is not None:
            if model_candidate.ambiguity == "clear":
                self.model_aggregator.apply(decision, baseline, model_candidate)
            else:
                self.model_aggregator.mark_fallback(decision, "NO_CLASSIFICATION_CANDIDATE")
                model_fallback_engaged = True
        elif model_result is not None:
            self.model_aggregator.mark_fallback(decision, normalise_fallback(model_result))
            model_fallback_engaged = True

        # Stage b' — generic deterministic derived refinements (application layer).
        matched_derived = self.derived_engine.apply(decision, ctx)

        # If no business classification survived, fill safe defaults but PRESERVE
        # any safety-terminal or prompt-injection routing already established. A
        # detected secret or injection must never be dropped to a model-eligible
        # generic fallback: it stays a provisional fallback that keeps
        # bypass_sensitive / bypass_untrusted_input.
        const = self.final_policy.const
        fallback_engaged = decision.category is None or decision.intent is None
        if fallback_engaged:
            if decision.category is None:
                decision.set_scalar("category", const.general_category, stage="manual_fallback")
            if decision.intent is None:
                decision.set_scalar("intent", const.unclassified_intent, stage="manual_fallback")
            decision.add_values("risk_flags", ["classification_uncertain"], stage="manual_fallback")
            decision.add_values("reason_codes", ["UNCLASSIFIED_MANUAL_REVIEW"], stage="manual_fallback")
            decision.decision_basis = "manual_fallback"
        fallback_engaged = fallback_engaged or model_fallback_engaged

        # Stage d — final policy.
        self.final_policy.apply_routing(decision, ctx)
        self.final_policy.refine_sensitive_bypass_reason(decision, ctx)
        # Stage e — market overlay.
        note = self.final_policy.apply_overlay(decision, ctx)
        # Stage f — rationale.
        rationale = self.final_policy.render_rationale(decision)

        decision_dict = assemble_decision(
            message,
            decision,
            market_applicability_note=note,
            short_rationale=rationale,
            processing_status="provisional_fallback" if fallback_engaged else "classified",
            model_called=bool(model_result and model_result.called),
        )

        model_trace = ModelTraceBuilder.build(
            mode=self.model_gate.mode,
            provider_name=self.semantic_classifier.name,
            rules_candidate=rules_candidate,
            invocation=invocation,
            final_decision=decision_dict,
        )

        # Stage g — JSON Schema validation.
        schema_errors = self._schema_errors(decision_dict)
        # Stage h — semantic validation.
        violations = self.semantic_validator.validate(
            decision_dict, ctx, model_mode=self.model_gate.mode
        )

        if schema_errors or violations:
            return self._fallback(
                message,
                ctx,
                decision,
                baseline,
                matched_pre,
                matched_post,
                matched_derived,
                "UNCLASSIFIED_MANUAL_REVIEW",
                schema_valid=not schema_errors,
                violations=violations,
                model_trace=model_trace,
            )

        return ClassificationResult(
            decision=decision_dict,
            trace=tuple(decision.trace),
            matched_pre_model=tuple(matched_pre),
            matched_post_semantic=tuple(matched_post),
            matched_derived=tuple(matched_derived),
            baseline_rule_ids=tuple(baseline.matched_rule_ids),
            refinement_ids=tuple(baseline.refinement_ids),
            schema_valid=True,
            semantic_violations=(),
            model_trace=model_trace,
        )

    # -- helpers ------------------------------------------------------------
    def _aggregate(self, decision: WorkingDecision, baseline: BaselineOutcome) -> None:
        if decision.category is None and baseline.category is not None:
            decision.set_scalar("category", baseline.category, stage="baseline_semantic")
        if decision.intent is None and baseline.intent is not None:
            decision.set_scalar("intent", baseline.intent, stage="baseline_semantic")
        elif (
            decision.intent is not None
            and baseline.intent is not None
            and baseline.intent != decision.intent
        ):
            decision.add_values("secondary_intents", [baseline.intent], stage="aggregation")

        # Routing captured by a refinement whose ``when.intent`` matched.
        for field_name, value in baseline.routing_set.items():
            if field_name == "minimum_priority":
                assert isinstance(value, str)
                decision.raise_minimum(value, stage="baseline_semantic")
            elif getattr(decision, field_name) is None:
                decision.set_scalar(field_name, value, stage="baseline_semantic")

        decision.add_values("risk_flags", baseline.risk_flags, stage="baseline_semantic")
        decision.add_values("reason_codes", baseline.reason_codes, stage="baseline_semantic")
        decision.add_values("secondary_teams", baseline.secondary_teams, stage="baseline_semantic")
        decision.add_values("secondary_intents", baseline.secondary_intents, stage="baseline_semantic")

    def _apply_ingestion_eligibility(
        self, decision: WorkingDecision, ctx: SignalContext
    ) -> None:
        """Preserve ingestion bypasses even if no policy rule matched them."""

        state = ctx.ingestion_eligibility_state
        if state == "eligible" or decision.model_eligibility is not None:
            return
        if state == "bypass_sensitive":
            decision.set_scalar("model_eligibility", state, stage="pre_model_safety")
            decision.set_scalar(
                "model_bypass_reason",
                ctx.ingestion_eligibility_reason
                or "sensitive_payment_or_authentication_data",
                stage="pre_model_safety",
            )
        elif state == "bypass_attachment":
            decision.set_scalar("model_eligibility", state, stage="pre_model_safety")
            decision.set_scalar(
                "model_bypass_reason",
                ctx.ingestion_eligibility_reason or "attachment_received_body_insufficient",
                stage="pre_model_safety",
            )
        elif state == "bypass_untrusted_input":
            decision.set_scalar("model_eligibility", state, stage="pre_model_safety")
            decision.set_scalar(
                "model_bypass_reason",
                ctx.ingestion_eligibility_reason or "prompt_injection_detected",
                stage="pre_model_safety",
            )
            decision.add_values(
                "risk_flags", ["prompt_injection_detected"], stage="pre_model_safety"
            )
        elif state in {"redaction_uncertain", "invalid_input"}:
            # The output vocabulary has no direct invalid/uncertain eligibility
            # value. Use the conservative sensitive bypass with the approved
            # redaction-uncertain reason; the gate record retains the exact cause.
            decision.set_scalar("model_eligibility", "bypass_sensitive", stage="pre_model_safety")
            decision.set_scalar(
                "model_bypass_reason", "redaction_uncertain", stage="pre_model_safety"
            )
            decision.add_values(
                "risk_flags", ["redaction_uncertain"], stage="pre_model_safety"
            )
            decision.add_values(
                "reason_codes", ["REDACTION_UNCERTAIN"], stage="pre_model_safety"
            )

    def _add_reference_flags(self, decision: WorkingDecision, ctx: SignalContext) -> None:
        """Surface attachment/passport reference detections as risk flags."""

        if ctx.attachment_referenced:
            decision.add_values("risk_flags", ["attachment_referenced"], stage="aggregation")
        if ctx.flag("passport_referenced"):
            decision.add_values("risk_flags", ["passport_referenced"], stage="aggregation")

    def _demote_overridden_intent(self, decision: WorkingDecision, baseline: BaselineOutcome) -> None:
        """When a deterministic rule set the primary intent, keep the baseline top as secondary."""

        top = baseline.top_intent
        if (
            decision.terminal_rule_fired
            and top is not None
            and top != decision.intent
            and top not in decision.secondary_intents
        ):
            decision.add_values("secondary_intents", [top], stage="aggregation")

    def _schema_errors(self, decision_dict: dict[str, Any]) -> list[str]:
        schema_id = self.config.schema_registry.ids.get(_OUTPUT_SCHEMA_FILE)
        if schema_id is None:  # pragma: no cover - registry always has it
            return ["output schema not registered"]
        validator = self.config.schema_registry.validator(schema_id)
        return [error.message for error in validator.iter_errors(decision_dict)]

    def _fallback(
        self,
        message: IngestedMessage,
        ctx: SignalContext,
        decision: WorkingDecision,
        baseline: BaselineOutcome,
        matched_pre: list[str],
        matched_post: list[str],
        matched_derived: list[str],
        reason: str,
        *,
        schema_valid: bool = True,
        violations: list[Violation] | None = None,
        model_trace: ModelDecisionTrace,
    ) -> ClassificationResult:
        note = self.final_policy.apply_overlay(decision, ctx)
        rationale = self.final_policy.rationale_templates.get(
            reason, "Manual review required; no safe automated classification."
        )
        fallback = manual_fallback_decision(
            message,
            reason=reason,
            short_rationale=rationale,
            market_applicability_note=note,
            model_eligibility=decision.model_eligibility or "eligible",
            model_bypass_reason=decision.model_bypass_reason,
            model_called=model_trace.called,
            preserved_risk_flags=tuple(decision.risk_flags),
            preserved_reason_codes=tuple(decision.reason_codes),
        )
        decision.trace.append(TraceEntry(stage="manual_fallback", rule_id=None, fields=("category", "intent")))
        return ClassificationResult(
            decision=fallback,
            trace=tuple(decision.trace),
            matched_pre_model=tuple(matched_pre),
            matched_post_semantic=tuple(matched_post),
            matched_derived=tuple(matched_derived),
            baseline_rule_ids=tuple(baseline.matched_rule_ids),
            refinement_ids=tuple(baseline.refinement_ids),
            schema_valid=schema_valid,
            semantic_violations=tuple(violations or ()),
            model_trace=model_trace,
        )
