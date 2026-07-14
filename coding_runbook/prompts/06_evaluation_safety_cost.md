# Phase 06 — Evaluation, Safety Gates, Regression and Cost Measurements

Prerequisite: Phase 05 passes.

Read:
- `policy/ground_truth_40.jsonl`
- `policy/safety_assertions.json`
- `policy/evaluation_policy.md`

Implement:
- Ground-truth comparison for policy fields; ignore runtime-dependent `model_called` and `decision_basis` except where bypass policy forbids model use.
- Per-category precision, recall and F1; macro F1; confusion matrix.
- Priority, route and assigned-team exact agreement.
- High-risk recall and explicit false-negative list.
- Auto-response safety and template-ID agreement.
- Model bypass rate, manual-review rate, fallback count, schema failure count, median/p95 latency.
- Near-duplicate consistency and repeat-linkage checks.
- Machine-executable hard gates from `safety_assertions.json`.
- Synthetic red-team fixtures A01–A04.
- Regression command comparing a candidate run with a known-good run.
- Formula-driven cost summary using measured bypass, latency and review-rate scenarios. OpenAI pricing must remain clearly hypothetical and not selected.

Generate:
- `output/evaluation_summary.json`
- `output/evaluation_report.md`
- `output/mismatch_report.csv`
- `output/confusion_matrix.csv`
- `output/safety_gate_results.json`
- `output/cost_assumptions.json`

Do not claim production accuracy or compliance.
Write `docs/phase_reports/phase_06.md` and stop.
