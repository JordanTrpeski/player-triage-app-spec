# Two-Page Decision Log Outline

## 1. Decision and scope
- Provider-independent local triage prototype for 40 supplied messages and approximately 900/day production volume.
- Exactly eight categories, four priorities, three routes, and fixed teams.
- No autonomous account, payment, KYC, fraud, regulator, or self-exclusion actions.

## 2. Architecture
- Local input validation, sensitive-data detection/redaction, deterministic high-risk rules, optional local LLM for eligible ambiguity, deterministic policy overrides, CSV and JSONL.
- OpenAI API evaluated but not selected because public Usage Policies prohibit real-money gambling without explicit authorization.

## 3. Safety decisions
- Explicit RG, underage, self-harm, active compromise, CVV/authentication data and redaction uncertainty bypass the model.
- Attachments are not processed by the model.
- Prompt injection is treated as untrusted data; no tools or authority.
- Human review for all account-specific, high-risk, complaint, KYC, payment and game-result cases.

## 4. Privacy and audit
- Raw messages remain in the authorized source file/system.
- CSV/JSONL contain no raw message or sensitive values.
- Audit events record versions, rule IDs, decisions, fallbacks, overrides, and configuration changes.

## 5. Evaluation and live walkthrough
- Ground truth for 40 supplied messages; hard safety gates are non-compensatory.
- Report mismatches honestly; 40 cases do not establish production accuracy.
- Demonstrate configuration change, regression diff, and rollback without weakening critical controls.

## 6. Cost and production gaps
- Volume is modest; human review, engineering, security and governance likely dominate inference cost.
- Production requires representative evaluation, privacy/security approval, model provenance, access/retention controls, reliable queues, monitoring and staffing.
