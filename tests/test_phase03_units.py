"""Unit tests for the Phase 03 stages using synthetic signal contexts.

No dataset text is used here — every context is a synthetic string, so these
tests never echo real player content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from player_triage.baseline_classifier import BaselineClassifier
from player_triage.config import AppConfig, load_app_config
from player_triage.final_policy import FinalPolicy
from player_triage.rule_engine import RuleEngine
from player_triage.signals import SignalContext
from player_triage.validation import SemanticValidator
from player_triage.working import WorkingDecision, max_priority


@pytest.fixture(scope="module")
def config(app_root: Path) -> AppConfig:
    return load_app_config(app_root)


@pytest.fixture(scope="module")
def rule_engine(config: AppConfig) -> RuleEngine:
    return RuleEngine.from_policy(config.component("policy_rules"))


@pytest.fixture(scope="module")
def classifier(config: AppConfig) -> BaselineClassifier:
    return BaselineClassifier.from_policy(config.component("baseline_intent_rules"))


@pytest.fixture(scope="module")
def final_policy(config: AppConfig) -> FinalPolicy:
    return FinalPolicy.from_config(
        config.component("auto_response_templates"),
        config.component("baseline_intent_rules"),
        config.component("rationale_templates"),
    )


@pytest.fixture(scope="module")
def validator(config: AppConfig) -> SemanticValidator:
    return SemanticValidator.from_config(config)


def make_ctx(
    text: str = "",
    *,
    flags: Mapping[str, bool] | None = None,
    previous_contact_count: int = 0,
    market_framework_status: str = "established",
    **kwargs: object,
) -> SignalContext:
    base_flags: dict[str, bool] = {
        "cvv_detected": False,
        "auth_secret_detected": False,
        "pan_detected": False,
        "card_context_detected": False,
        "prompt_injection_detected": False,
        "identity_document_number_detected": False,
        "repeat_contact": previous_contact_count >= 1,
        "contains_bonus_context": False,
        "account_specific": False,
        "claimed_missing_win": False,
        "explicit_expected_vs_received_amount": False,
        "passport_referenced": False,
    }
    if flags:
        base_flags.update(flags)
    return SignalContext(
        msg_id=kwargs.get("msg_id", "M00"),  # type: ignore[arg-type]
        text=text,
        flags=base_flags,
        sensitive_data_types=(),
        previous_contact_count=previous_contact_count,
        first_contact_message_id=None,
        related_message_ids=(),
        attachment_received=False,
        attachment_referenced=bool(kwargs.get("attachment_referenced", False)),
        identity_document_referenced=bool(kwargs.get("identity_document_referenced", False)),
        market=str(kwargs.get("market", "Malta")),
        market_overlay_codes=(),
        market_framework_status=market_framework_status,
        ingestion_eligibility_state="eligible",
        ingestion_eligibility_reason=None,
    )


# -- priority helper --------------------------------------------------------
def test_max_priority_orders_correctly() -> None:
    assert max_priority("low", "high") == "high"
    assert max_priority("critical", "high") == "critical"
    assert max_priority(None, "medium") == "medium"
    assert max_priority("medium", None) == "medium"


# -- deterministic safety rules --------------------------------------------
def test_self_harm_is_terminal_critical(rule_engine: RuleEngine) -> None:
    decision = WorkingDecision(msg_id="M00")
    ctx = make_ctx("i want to end my life, please help")
    matched = rule_engine.evaluate_pre_model(decision, ctx)
    assert "SELF_HARM_SIGNAL" in matched
    assert decision.category == "Responsible Gambling"
    assert decision.priority == "critical"
    assert decision.route == "specialist"
    assert decision.terminal_rule_fired is True
    assert "self_harm_signal" in decision.risk_flags


def test_pci_sets_routing_without_category(rule_engine: RuleEngine) -> None:
    decision = WorkingDecision(msg_id="M00")
    ctx = make_ctx("payment problem", flags={"cvv_detected": True})
    rule_engine.evaluate_pre_model(decision, ctx)
    assert decision.priority == "critical"
    assert decision.assigned_team == "Payments Security"
    assert decision.model_eligibility == "bypass_sensitive"
    # PCI rule intentionally does not set category/intent.
    assert decision.category is None
    assert decision.intent is None


def test_precedence_first_terminal_wins(rule_engine: RuleEngine) -> None:
    # Self-harm (order 5) precedes self-exclusion (order 20); both texts present.
    decision = WorkingDecision(msg_id="M00")
    ctx = make_ctx("i want to kill myself and permanently close my account and self-exclude")
    rule_engine.evaluate_pre_model(decision, ctx)
    assert decision.intent == "credible_self_harm"
    assert decision.category == "Responsible Gambling"


def test_multiple_simultaneous_matches_accumulate(rule_engine: RuleEngine) -> None:
    # Underage (terminal, order 40) + third-party payment (non-terminal, order 45).
    decision = WorkingDecision(msg_id="M00")
    ctx = make_ctx("my son is 16 and underage; my son used my card to deposit")
    matched = rule_engine.evaluate_pre_model(decision, ctx)
    assert "UNDERAGE_GAMBLING_REPORTED" in matched
    assert "THIRD_PARTY_PAYMENT_REPORTED" in matched
    assert "UNDERAGE_GAMBLING_REPORTED" in decision.reason_codes
    assert "THIRD_PARTY_PAYMENT_REPORTED" in decision.reason_codes
    assert decision.category == "Fraud & Compliance"


def test_prompt_injection_non_terminal(rule_engine: RuleEngine) -> None:
    decision = WorkingDecision(msg_id="M00")
    ctx = make_ctx("where is my withdrawal", flags={"prompt_injection_detected": True})
    rule_engine.evaluate_pre_model(decision, ctx)
    assert decision.model_eligibility == "bypass_untrusted_input"
    assert decision.terminal_rule_fired is False
    assert "prompt_injection_detected" in decision.risk_flags


def test_post_semantic_skipped_after_terminal(rule_engine: RuleEngine) -> None:
    decision = WorkingDecision(msg_id="M00")
    ctx = make_ctx("i will self-exclude permanently and file a formal complaint")
    rule_engine.evaluate_pre_model(decision, ctx)
    matched_post = rule_engine.evaluate_post_semantic(decision, ctx)
    assert matched_post == []  # safety terminal outranks the complaint override
    assert decision.category == "Responsible Gambling"


# -- baseline scoring / tie-break ------------------------------------------
def test_baseline_scoring_is_deterministic(classifier: BaselineClassifier) -> None:
    ctx = make_ctx("my withdrawal is pending and stuck, please process it")
    first = classifier.classify(ctx)
    second = classifier.classify(ctx)
    assert first.intent == second.intent
    assert first.intent == "withdrawal_status_first_contact"


def test_baseline_highest_score_wins(classifier: BaselineClassifier) -> None:
    # 'duplicate' (score 95) should beat a co-occurring lower-scored match.
    ctx = make_ctx("i was charged twice, a duplicate charge on my card")
    outcome = classifier.classify(ctx)
    assert outcome.intent == "duplicate_card_charge"


def test_repeat_contact_refinement(classifier: BaselineClassifier) -> None:
    ctx = make_ctx(
        "my withdrawal is still pending, where is my money", previous_contact_count=1
    )
    outcome = classifier.classify(ctx)
    assert outcome.intent == "withdrawal_repeated_unresolved"
    assert outcome.routing_set.get("minimum_priority") == "high"


# -- final policy -----------------------------------------------------------
def test_defaults_are_conservative(final_policy: FinalPolicy) -> None:
    decision = WorkingDecision(msg_id="M00", category="Payments & Withdrawals", intent="missing_deposit")
    final_policy.apply_routing(decision, make_ctx("deposit not showing"))
    assert decision.priority == "medium"
    assert decision.route == "human"
    assert decision.assigned_team == "Payments Operations"
    assert decision.human_review_required is True


def test_static_template_auto_response(final_policy: FinalPolicy) -> None:
    decision = WorkingDecision(
        msg_id="M00", category="Bonuses & Promotions", intent="wagering_requirement_information"
    )
    final_policy.apply_routing(decision, make_ctx("what are the wagering requirements"))
    assert decision.route == "auto_respond"
    assert decision.priority == "low"
    assert decision.auto_response_template_id == "FAQ_BONUS_WAGERING_REQUIREMENT"
    assert decision.human_review_required is False


def test_account_specific_blocks_auto_response(final_policy: FinalPolicy) -> None:
    decision = WorkingDecision(
        msg_id="M00", category="Bonuses & Promotions", intent="wagering_requirement_information"
    )
    final_policy.apply_routing(
        decision, make_ctx("wagering question", flags={"account_specific": True})
    )
    assert decision.route == "human"
    assert decision.auto_response_template_id is None


def test_india_overlay_adds_compliance_and_blocks_auto(final_policy: FinalPolicy) -> None:
    decision = WorkingDecision(
        msg_id="M00", category="General", intent="compliment_no_action"
    )
    ctx = make_ctx("great service", market_framework_status="prohibited_market", market="India")
    final_policy.apply_routing(decision, ctx)
    note = final_policy.apply_overlay(decision, ctx)
    assert "Market Compliance" in decision.secondary_teams
    assert "INDIA_MARKET_OVERLAY" in decision.reason_codes
    assert decision.route != "auto_respond"
    assert note is not None


def test_bypass_reason_pan_and_cvv(final_policy: FinalPolicy) -> None:
    # Both PAN and CVV detected -> the specific pan_and_cvv_detected reason.
    decision = WorkingDecision(msg_id="M00", model_eligibility="bypass_sensitive")
    decision.set_scalar(
        "model_bypass_reason", "sensitive_payment_or_authentication_data", stage="pre_model_safety"
    )
    ctx = make_ctx("payment card issue", flags={"pan_detected": True, "cvv_detected": True})
    final_policy.refine_sensitive_bypass_reason(decision, ctx)
    assert decision.model_bypass_reason == "pan_and_cvv_detected"


def test_bypass_reason_cvv_only_keeps_general(final_policy: FinalPolicy) -> None:
    decision = WorkingDecision(msg_id="M00", model_eligibility="bypass_sensitive")
    decision.set_scalar(
        "model_bypass_reason", "sensitive_payment_or_authentication_data", stage="pre_model_safety"
    )
    ctx = make_ctx("cvv exposure", flags={"cvv_detected": True, "pan_detected": False})
    final_policy.refine_sensitive_bypass_reason(decision, ctx)
    assert decision.model_bypass_reason == "sensitive_payment_or_authentication_data"


def test_bypass_reason_auth_secret_only_keeps_general(final_policy: FinalPolicy) -> None:
    decision = WorkingDecision(msg_id="M00", model_eligibility="bypass_sensitive")
    decision.set_scalar(
        "model_bypass_reason", "sensitive_payment_or_authentication_data", stage="pre_model_safety"
    )
    ctx = make_ctx("password exposure", flags={"auth_secret_detected": True})
    final_policy.refine_sensitive_bypass_reason(decision, ctx)
    assert decision.model_bypass_reason == "sensitive_payment_or_authentication_data"


def test_bypass_reason_untouched_when_not_sensitive_bypass(final_policy: FinalPolicy) -> None:
    # A non-sensitive-bypass decision is never rewritten even if flags coincide.
    decision = WorkingDecision(msg_id="M00", model_eligibility="eligible")
    ctx = make_ctx("card talk", flags={"pan_detected": True, "cvv_detected": True})
    final_policy.refine_sensitive_bypass_reason(decision, ctx)
    assert decision.model_bypass_reason is None


def test_rationale_rendered_from_templates(final_policy: FinalPolicy) -> None:
    decision = WorkingDecision(msg_id="M00")
    decision.add_values("reason_codes", ["MARKETING_OPTOUT_ONLY"], stage="final_policy")
    rendered = final_policy.render_rationale(decision)
    assert rendered  # non-empty
    assert len(rendered) <= 240
    # No digits (thus no sensitive value) in the approved marketing template.
    assert not any(ch.isdigit() for ch in rendered)


# -- semantic validator rejection cases ------------------------------------
def _valid_decision() -> dict[str, object]:
    return {
        "route": "human",
        "priority": "medium",
        "auto_response_template_id": None,
        "human_review_required": True,
        "model_eligibility": "eligible",
        "model_bypass_reason": None,
        "model_called": False,
        "risk_flags": [],
        "secondary_teams": [],
        "market_framework_status": "established",
        "category": "General",
        "intent": "login_password_reset_failure",
        "assigned_team": "General Support",
        "auto_response_policy": "acknowledgment_only",
        "decision_basis": "rules_only_baseline",
        "processing_status": "classified",
        "short_rationale": "Routine.",
        "market_applicability_note": None,
        "secondary_intents": [],
        "reason_codes": [],
        "market_overlay_codes": [],
        "sensitive_data_types": [],
        "required_context": [],
        "missing_context": [],
    }


def _codes(validator: SemanticValidator, decision: dict[str, object]) -> set[str]:
    return {v.code for v in validator.validate(decision, make_ctx())}


def test_semantic_clean_decision_passes(validator: SemanticValidator) -> None:
    assert _codes(validator, _valid_decision()) == set()


def test_semantic_rejects_auto_without_template(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(route="auto_respond", priority="low", auto_response_policy="allowed_template",
             human_review_required=False, auto_response_template_id=None)
    assert "AUTO_RESPOND_WITHOUT_TEMPLATE" in _codes(validator, d)


def test_semantic_rejects_auto_with_human_review(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(route="auto_respond", priority="low", auto_response_template_id="ACK_COMPLIMENT",
             human_review_required=True)
    assert "AUTO_RESPOND_WITH_HUMAN_REVIEW" in _codes(validator, d)


def test_semantic_rejects_auto_non_low(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(route="auto_respond", priority="medium", auto_response_template_id="ACK_COMPLIMENT",
             human_review_required=False)
    assert "AUTO_RESPOND_NON_LOW_PRIORITY" in _codes(validator, d)


def test_semantic_rejects_critical_without_specialist(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(priority="critical", route="human")
    assert "CRITICAL_WITHOUT_SPECIALIST" in _codes(validator, d)


def test_semantic_rejects_model_called(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(model_called=True)
    assert "MODEL_CALLED_IN_RULES_ONLY" in _codes(validator, d)


def test_semantic_rejects_bypass_without_reason(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(model_eligibility="bypass_sensitive", model_bypass_reason=None)
    assert "BYPASS_WITHOUT_REASON" in _codes(validator, d)


def test_semantic_rejects_eligible_with_reason(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(model_eligibility="eligible", model_bypass_reason="prompt_injection_detected")
    assert "ELIGIBLE_WITH_BYPASS_REASON" in _codes(validator, d)


def test_semantic_rejects_injection_bypass_without_flag(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(model_eligibility="bypass_untrusted_input", model_bypass_reason="prompt_injection_detected",
             risk_flags=[])
    assert "INJECTION_BYPASS_WITHOUT_FLAG" in _codes(validator, d)


def test_semantic_rejects_prohibited_market_auto(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(route="auto_respond", priority="low", auto_response_template_id="ACK_COMPLIMENT",
             human_review_required=False, market_framework_status="prohibited_market",
             secondary_teams=["Market Compliance"])
    assert "PROHIBITED_MARKET_AUTO_RESPONSE" in _codes(validator, d)


def test_semantic_rejects_unknown_vocab(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(category="Not A Real Category")
    assert "UNKNOWN_VOCAB_VALUE" in _codes(validator, d)


def test_semantic_rejects_account_specific_auto(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(route="auto_respond", priority="low", auto_response_template_id="ACK_COMPLIMENT",
             human_review_required=False, decision_basis="rules_only_baseline")
    codes = {v.code for v in validator.validate(d, make_ctx(flags={"account_specific": True}))}
    assert "ACCOUNT_SPECIFIC_AUTO_RESPONSE" in codes


def test_semantic_rejects_raw_sensitive_in_rationale(validator: SemanticValidator) -> None:
    d = _valid_decision()
    d.update(short_rationale="card 4539 1488 0343 6467 was exposed")
    assert "RAW_SENSITIVE_VALUE" in _codes(validator, d)
