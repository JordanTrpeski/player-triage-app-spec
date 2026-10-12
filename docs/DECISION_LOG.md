# Decision Log

Key design decisions behind the triage engine, and why they were made. Read this before changing the runtime, the policy model or the safety rules.

## 1. Ship a deterministic rules-only runtime

**Context.** The original plan was to classify with a small local LLM. A provider-independent adapter was built and benchmarked: Qwen2.5-0.5B-Instruct (GGUF, q4_k_m) on CPU via llama-cpp-python.

**Choice.** The runtime is `rules_only`. The model adapter, eligibility gate and tests stay in the codebase, but the model is disabled and never loaded.

**Trade-off.** On a synthetic holdout the model did not meaningfully improve intent accuracy over the rules. It added about 1.4 s per inference (the rules engine takes about 4 ms per message) plus model-provenance and installation overhead. It could never have been given authority over safety fields anyway. The cost is that rules only cover phrasings someone has written down. New wording requires a policy change, not retraining.

## 2. Keep business rules in versioned JSON, not code

**Context.** Taxonomy, routing, thresholds, market overlays and redaction patterns change more often than the engine does, and those changes need review and rollback.

**Choice.** All policy lives in `policy/` as JSON, validated against `schemas/` and versioned as a single hash-verified bundle. The engine interprets policy and has no message-specific branches.

**Trade-off.** Adding a new kind of rule may require extending the rule DSL (`policy/rule_dsl.md`) and its schema, which is slower than writing an `if` statement. In return, policy changes can be reviewed, diffed and rolled back without a code release.

## 3. Deterministic policy is authoritative; any model is a proposer only

**Context.** A model might be re-enabled in future, so its authority needed defining in advance.

**Choice.** Eligibility, safety flags, priority, route, team, the human-review requirement and auto-responses are always decided by deterministic policy. A model may only propose category, intent, secondary intents, signals and ambiguity, and it can never lower a safety outcome.

**Trade-off.** This caps how much a model could ever improve results. That is intentional: the fields that carry risk stay auditable and reproducible.

## 4. Treat high-risk signals as terminal, locked rules

**Context.** Some messages must never be misrouted: self-harm, explicit self-exclusion, underage play, active account takeover, exposed payment or authentication data, and cases where redaction is uncertain.

**Choice.** These match terminal rules that skip all later classification and force specialist routing with human review. They are locked against editing through the normal console. Self-exclusion detection includes German phrasings, with guards for negated, informational and quoted mentions.

**Trade-off.** The rules are conservative and will over-escalate some benign messages. A false positive costs a human a few minutes. A false negative is a compliance incident.

## 5. Detect and redact sensitive data before any downstream step

**Context.** Messages can contain card numbers, CVVs, OTPs, PINs, recovery codes, identity numbers and player IDs.

**Choice.** Detection and redaction run locally, immediately after normalisation. Messages containing such data are marked `bypass_sensitive` and would never be sent to a model.

**Trade-off.** Pattern-based detection is not full data-loss prevention and will miss formats it has no pattern for. It is a first line of defence, not a guarantee.

## 6. Treat prompt-injection attempts as untrusted data

**Context.** Players can paste text that tries to instruct an automated system.

**Choice.** Messages that match prompt-injection patterns are marked `bypass_untrusted_input` and handled by rules alone. The injected text cannot change category, priority, route or output schema.

**Trade-off.** Legitimate messages that happen to match an injection pattern lose any model assistance. With the model disabled this has no practical cost today.

## 7. Fail closed on validation

**Context.** A malformed or contradictory decision is worse than no decision.

**Choice.** Every decision is checked against the output schema and semantic constraints (`policy/semantic_constraints.json`). A decision that fails is not emitted as a normal result; the message is isolated and reported, and the rest of the batch continues.

**Trade-off.** One bad record can't contaminate the batch, but a policy bug shows up as failed records rather than a degraded best guess.

## 8. Keep raw content out of outputs; make the audit trail append-only

**Context.** Outputs and audit logs get shared more widely than the raw input.

**Choice.** The decision CSV and JSONL contain no raw message text, player identifiers or sensitive values. Audit events are append-only (JSONL plus SQLite) and record the policy version, component digests, triggered rule IDs, fallbacks, overrides and configuration changes. Each run writes a manifest with a decision digest so results can be reproduced.

**Trade-off.** Reviewing a decision requires access to the original input. That is acceptable, because access to the input should be restricted anyway.

## 9. Keep consequential actions human-controlled

**Context.** Responsible-gambling, payment, KYC, fraud and account actions carry regulatory consequences.

**Choice.** The system classifies, prioritises, routes and audits, and stops there. Routing to a human or specialist team is a normal outcome, not a failure.

**Trade-off.** Staffing, not compute, dominates operating cost. At an illustrative 900 messages a day, roughly three quarters of messages go to human or specialist queues.

## 10. Govern policy changes through the console, localhost only

**Context.** Operators need to tune rules and thresholds without editing JSON by hand or bypassing review.

**Choice.** The Streamlit console binds to `127.0.0.1`. Its Policy Studio enforces draft → validate → impact preview → activate → rollback. Locked safety rules and model settings cannot be edited there.

**Trade-off.** There is no multi-user authentication or remote access. Both would be required before shared use.

## 11. Keep evaluation datasets separate

**Context.** It is easy to overstate accuracy by mixing tuning data, regression cases and live batches.

**Choice.** The 40-message benchmark, the synthetic holdouts and imported operational batches are reported separately. Unlabelled imports are never presented as accuracy measurements.

**Trade-off.** The reported numbers are narrower and less flattering, but each number means what it says.

## Known limitations

- **Small labelled data.** Benchmark agreement comes from 40 labelled messages plus synthetic holdouts, which is not enough to establish production accuracy. One known mismatch remains: message M22 is classified as `withdrawal_status_first_contact` where the label is `withdrawal_delay`. A representative labelled set is the main prerequisite for further tuning.
- **Limited non-English coverage.** Only a few languages have phrasings written into the rules.
- **No production infrastructure.** Queues, retries, monitoring, access control and retention policies are not implemented.
