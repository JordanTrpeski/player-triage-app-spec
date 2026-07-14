# Phase 00 — Repository and Policy Audit

You are working in the repository root. Do not write application code in this phase.

Read in this order:
1. `coding_runbook/agent_operating_rules.md`
2. `policy/README.md`
3. `policy/stage9_policy_spec.md`
4. `policy/controlled_vocabularies.json`
5. `schemas/output_schema.json`
6. `schemas/ground_truth_schema.json`
7. `schemas/audit_event_schema.json`
8. `policy/ground_truth_40.jsonl`
9. `policy/safety_assertions.json`
10. `tools/validate_policy_package.py`

Tasks:
- Run `python tools/validate_policy_package.py`.
- Confirm there are exactly 40 unique ground-truth records matching M01–M40.
- Confirm every enum/reference/template/team/reason/risk/context key is defined.
- Confirm the output and audit schemas compile.
- Confirm route/auto-response/model-bypass cross-field rules are internally consistent.
- Confirm the input workbook and CSV have matching 40 rows and headers.
- Write `docs/phase_reports/phase_00.md` using the template.

Do not modify policy files unless the validator identifies an objective serialization/reference defect. If one exists, document the proposed minimal fix and stop for user approval instead of silently changing policy meaning.

Stop after the phase report. Do not create `src/` application code.
