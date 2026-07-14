# Phase 03 — Deterministic Policy Engine and Rules-Only Baseline

Prerequisite: Phase 02 passes.

Read:
- `policy/rule_dsl.md`
- `policy/policy_rules.json`
- `policy/baseline_intent_rules.json`
- `policy/taxonomy.json`
- `policy/teams.json`
- `policy/auto_response_templates.json`
- `policy/ground_truth_40.jsonl`
- `policy/safety_assertions.json`

Implement:
- Generic rule evaluator for the documented DSL; do not hard-code message IDs.
- Pre-model deterministic safety rules with terminal precedence.
- Rules-only semantic baseline using scored intent rules and documented refinements.
- Multi-intent handling, priority maxing, owning team and secondary-team logic.
- Formal complaint/repeat-contact overrides.
- Auto-response cross-field enforcement and template selection.
- Market overlays without replacing the primary category.
- Final result construction and validation against `schemas/output_schema.json`.
- Rules-only manual fallback when no safe classification is available.

Run all 40 messages in `rules_only` mode.
Required outcome:
- 40 terminal schema-valid results or explicit fallbacks.
- All bypass safety gates for M07, M11, M15, M21, M23, M28 and M36 pass.
- M18 remains Payments & Withdrawals, medium, human, with injection flag.
- M12/M27/M34 are consistent.
- M14 is human-routed pending template approval.

Generate a temporary mismatch report but do not alter ground truth to improve results.
Write `docs/phase_reports/phase_03.md` and stop.
