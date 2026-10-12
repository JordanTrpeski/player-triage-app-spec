# Decision Log — Player Contact Triage

Active bundle `policy-3.3.1` · runtime `rules_only` · model conclusion
`model_rejected_no_material_improvement` · Python 3.12 · canonical decision digest
`a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b`.

## Page 1 — What was built and why

**Problem and scope.** A local, provider-independent prototype that triages
player-support messages into a fixed taxonomy (8 categories, 4 priorities, 3
routes, named teams) for the 40 supplied messages and an illustrative ~900/day.
No autonomous account, payment, KYC, fraud, regulator or self-exclusion actions.

**Architecture.** Input validation → normalization + repeat-contact linkage →
sensitive detection/redaction → model-eligibility gate → deterministic terminal
safety rules → rules-only classification → deterministic final policy + market
overlays → output-schema + semantic validation (fail closed) → CSV/JSONL/SQLite/
audit + local console. An optional local LLM sits only at the classification step
as a *proposer* and is currently disabled.

**Rules vs AI vs human.** Deterministic policy is authoritative for eligibility,
safety, priority, route, team, human-review, auto-response and market overlays. A
model may only ever propose category/intent/secondary-intents/signals/complaint/
ambiguity, and cannot lower any safety outcome. Humans perform all operational
actions (account, payment, KYC, self-exclusion); the system classifies and audits.

**Sensitive-data and prompt-injection controls.** PAN/CVV/authentication secrets/
OTP/PIN/recovery codes/identity numbers/player IDs are detected locally and
redacted before any downstream step; such cases become `bypass_sensitive` and
never reach a model. Prompt-injection text is treated as untrusted data →
`bypass_untrusted_input`, `model_called=false`; the injected request cannot change
category, priority, route or schema.

**Deterministic high-risk precedence.** Self-harm, explicit self-exclusion
(incl. German phrasings, with negation/informational/quoted guards), underage,
active account takeover, exposed payment/authentication data, and redaction
uncertainty are terminal, locked rules that bypass the model and force specialist
routing + human review.

**Outputs and auditability.** Decisions are written to CSV and JSONL with no raw
message text, player identifiers or sensitive values. Append-only audit events
(JSONL + SQLite) record policy version, component digests, triggered rule IDs,
final decision, fallbacks, overrides and configuration changes. A `run_manifest`
records a canonical decision digest for reproducibility.

**Local control console.** A localhost-only Streamlit console (8 pages) provides
dashboard, messages, human review, Policy Studio (governed draft → validate →
impact → activate → rollback), evaluation, audit explorer, configuration versions
and settings. No external ports, tools or model editing through the normal UI.

**Why the local model was rejected.** Phase 04 built a provider-independent
adapter and benchmarked a small permissive local model (Qwen2.5-0.5B-Instruct
GGUF q4_k_m, apache-2.0, CPU via llama-cpp-python; local benchmark load ≈0.7 s,
≈1.4 s/inference). On the independent synthetic semantic holdout it did not
**meaningfully** improve intent over rules-only, added latency and a model
provenance/install burden, and could not be granted authority over any safety
field. Conclusion: `model_rejected_no_material_improvement`. The adapter, gate,
governance and tests are retained as evidence; the model stays disabled.

## Page 2 — Evidence, limitations and recommendation

**Supplied-set results (demonstration-set agreement).** 40/40 schema-valid
decisions, 0 failed, 9 deterministic/privacy bypasses. Category 40/40; priority,
route and team 40/40; intent 39/40. Canonical decision digest matches the accepted
value above.

**Core mismatch and diagnostic differences.** The single core mismatch is **M22
intent** (`withdrawal_delay` expected vs `withdrawal_status_first_contact`) — a
short multilingual delay-vs-first-contact distinction; M22 category/priority/route/
team are correct. Separately there are **52 set-valued diagnostic differences**
(secondary-intent and risk-flag sets) that affect none of the five scored fields
and no safety gate.

**Safety-gate results.** 15/15 official hard gates pass; 26/26 locked activation
gates pass; activation recommendation `eligible_for_controlled_review`. No-call
tests prove the model is never invoked for M07/M11/M15/M18/M23 or any
secret/injection holdout case.

**Holdout results (synthetic).** Holdout-v1 (25 cases, discovered-defect
regression): category 22/25, intent 21/25, with the three originally-discovered
defects corrected (0 false positives / 0 false negatives on the recorded
findings). Holdout-v2 (18 new cases): 18/18 on every scored field; zero
sensitive-secret false negatives; zero prompt-injection cases on a model-eligible
path. These are synthetic and do not establish production accuracy.

**Performance and capacity (local benchmark).** Rules-only ≈22 messages/second
(fresh benchmark ≈21.75 msg/s; accepted-state reference 22.37 msg/s;
per-message ≈4 ms; peak Python allocation ≈2.8 MB). Illustrative 900-message daily
replay ≈40 s of compute — comfortably within a single machine. Not a
production-scale load test.

**Human-review workload (illustrative, 900/day).** ~360 human, ~315 specialist,
~225 auto-respond; ~90 critical and ~202 high priority per day — human review and
staffing dominate cost, not inference.

**Production-readiness limitations.** Metrics are demonstration/synthetic only; a
representative labelled evaluation, privacy/security sign-off, model provenance and
access/retention controls, reliable queues, monitoring and staffing are required
before production. Non-English coverage is limited; detection is conservative and
not complete DLP.

**Recommended next steps.** (1) Representative labelled evaluation set and
threshold tuning under governance; (2) privacy/security review and data-handling
approval; (3) reliability (queues, retries, monitoring) and access/retention
controls; (4) operational integration behind human action, never autonomous.

**Explicitly excluded autonomous actions.** No n8n/integration, email/chat
delivery, ticket assignment, account/payment actions, hosted APIs, production
authentication or deployment. This is a demonstration prototype — not production
proven, regulator approved, guaranteed secure, or fully compliant.
