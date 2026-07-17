# Phase 04 — optional local semantic model evaluation

## Outcome

Phase 04 implemented and safety-tested the optional local-model adapter, but the evaluated model is not approved for use. The active policy successor is `policy-3.3.1`; its model configuration remains `evaluation_only`, and `rules_only` remains fully operational.

The deciding evidence is non-compensatory: on the frozen 32-case independent semantic holdout, the local model produced no category, intent, secondary-intent, or assigned-team improvement, reduced final priority and route accuracy, and forced a conservative fallback for every case. Safety remained intact, but safety cannot compensate for absent semantic value.

## Provenance and feasibility profile

| Item | Evaluated value |
|---|---|
| Host | Microsoft Windows 11 Pro for Workstations, 64-bit, build 10.0.26200 |
| CPU | Intel Core i5-10400F, 6 cores / 12 logical processors |
| RAM | 15.9 GiB installed; approximately 6.7 GiB free during final verification |
| GPU | NVIDIA GeForce GTX 1070, 8 GiB; not used by the installed CPU runtime wheel |
| Python | 3.12.10, 64-bit |
| Runtime | `llama-cpp-python==0.3.34`, prebuilt CPU wheel |
| Model | `Qwen/Qwen2.5-0.5B-Instruct-GGUF:q4_k_m` |
| Model revision | `9217f5db79a29953eb74d5343926648285ec7e67` |
| Model license | Apache-2.0 |
| Artifact size | 491,400,032 bytes |
| Artifact SHA-256 | `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db` |
| Artifact location | User model directory outside the repository; no GGUF is tracked |
| Prompt | `classifier-prompt-1.0.0`, SHA-256 `30a19f73a0e36e95c34066b738379c784da5864ad5b2d84f0f202cc180a8caef` |
| Generation | temperature 0; JSON-schema constrained; at most one schema retry |

Only this one candidate model was evaluated. A second model was not attempted after the first candidate failed the meaningful-improvement and route non-decline gates.

## Adapter architecture and authority boundaries

The adapter is local-only and provider-independent at the engine boundary:

1. deterministic pre-model rules and ingestion eligibility run first;
2. deterministic post-semantic terminal rules run before a model request can be built;
3. `ModelCallGate` permits only redacted, eligible, supported-language, non-terminal input;
4. `ModelInvocationCoordinator` constructs the bounded request and invokes the provider;
5. the provider owns artifact/runtime/prompt integrity, constrained generation and one schema-only retry;
6. `CandidateValidator` enforces the strict candidate schema and rejects model-asserted safety facts;
7. `ModelCandidateAggregator` can add an eligible, clear semantic candidate but cannot remove deterministic safety state;
8. deterministic derived rules and final policy retain final routing authority;
9. `ModelTraceBuilder` and `ModelAuditBuilder` emit sanitized metadata only.

The engine has no `llama_cpp` import. The optional runtime is lazy-loaded inside an isolated worker, so deterministic classification remains understandable, testable and operational without the extra installed.

The request contract contains only redacted text plus controlled enums. It contains no raw text field, player ID, source row, original identifier, prompt transcript, raw model response, or hidden reasoning. Errors and audit events contain sanitized codes only.

## Policy history and German safety correction

### Preserved failed candidate: policy-3.3.0

The first candidate remains immutable in `policy/config_versions/policy-3.3.0`. Its manifest retains:

- policy-rules SHA-256 `1df7abc807638614825aa58470d2fb62a6e50ef5e629f8417ea334f8f364228c`;
- model-configuration SHA-256 `a5fc86cd6df75f6a58634ed3e9b016dbe986f01b26ef873be8445726d08fd21e`;
- original 16-case holdout SHA-256 `6f5ef1dd24522a78833444728d8880320431d5f7d56b8447894225ec93adc35b`.

The first rules-only observation was 16/16 valid, category 7/16, intent 5/16, secondary intent 16/16, priority 10/16, route 11/16, assigned team 7/16, 11 fallbacks, zero unsafe auto-responses and three bypasses. Its German M90 permanent self-exclusion wording was not deterministic and would reach the model. No complete real-model result is attributed to this failed candidate.

### Controlled successor: policy-3.3.1

`policy-3.3.1` extends the locked `RG_EXPLICIT_SELF_EXCLUSION` rule in authoritative policy configuration. It adds generic German positive forms for permanent account blocking, immediate exclusion, never gambling again and permanent gambling bans, together with negated, informational, attributed and quoted guards. There is no message-specific Python branch.

The active governed digests are:

| Component | Version | SHA-256 |
|---|---:|---|
| policy rules | 3.0.1 | `9be9d0e4bd3192b18223a91dff40512c745e9ec654435623800979dd5b0971ee` |
| model configuration | 1.0.1 | `d8740895230780ecdfdedc1b5b4f5cee321787a77eb2e2a2bdfdea67f9d4e07d` |
| research traceability | 3.0.1 | `5e73896ca53855217f208659ee1ef703502db6938bac5a5eea1ef4004e98b717` |
| UI editability | 3.0.1 | `b7a774729feefce484e79b1ec1182c9254dfd3dfd1dc963ad0aacd2da7df5f9d` |

Seven German positive fixtures now finish as critical Responsible Gambling specialist decisions with human review and zero model calls. Six negative/informational/attributed/quoted fixtures do not activate explicit self-exclusion. A negated fixture with an independent harm signal still routes critically to Responsible Gambling without being mislabeled as an explicit request. The rollback test restores `policy-3.3.0`, reproduces the adapter call for the preserved failed wording, then confirms `policy-3.3.1` blocks it deterministically.

## Real timeout behavior

The adapter does not claim that a Python thread or future stops native inference. A persistent spawned child process owns `llama.cpp`, and the parent permits only one outstanding inference. Each native inference has a 30-second bound. On expiry the parent terminates the worker, joins it, uses a hard kill if it remains alive, closes the pipe, and only then permits a replacement worker for a later message. Deterministic human fallback is returned and batch processing continues.

The process-termination test starts a worker that genuinely sleeps for 60 seconds, applies a short timeout, and verifies the child is no longer alive. No native call survives in the background.

The 30-second bound is per native generation, not per complete classification transaction. A schema-invalid first output may consume time and then receive its one allowed retry, so observed end-to-end p95 exceeded 30 seconds. That distinction is intentional and is not reported as a 30-second transaction SLA.

## Independent semantic holdout

The original 16-case file is preserved byte-for-byte. Eleven model-eligible entries from it retain their original text and expectations in the finalized set; its five deterministic safety/bypass entries remain in the preserved original and dedicated no-call suites, outside the model-quality denominator.

The finalized `phase04-semantic-holdout-2.0.0` contains 32 model-eligible cases, including 21 genuinely new cases authored before real-model execution. Its frozen SHA-256 is `a21d02c1a4b965f6edbd5b72a5212aa074af4fb6492abfca9794df41d4d21273`.

Coverage includes indirect withdrawal language; ordinary German support; Hindi, Macedonian and Romanian; complaint and dissatisfaction distinctions; bonus eligibility versus missing credit; KYC information versus withdrawal blocked by verification; game interruption versus result dispute; marketing opt-out versus ordinary closure; unknown-context reopening; short ambiguity; misspellings; mixed language and intent; insufficient information; polite indirect balance language; and frustration or sarcasm without escalation. Harm-linked closure is deliberately exercised in the separate safety-terminal no-call suite because including it in the semantic denominator would violate the requirement that every semantic case be model-eligible.

Each evaluation entry has a unique `case_id` (`P04-S001` through `P04-S032`). For an isolated batch it is mapped to a temporary valid operational ID (`M01` through `M32`); only the case ID is used in metric and mismatch reporting. Operational output continues to conform to `output_schema.json`.

For every case the evaluator creates a sanitized `SemanticCaseRecord` containing: case ID; model-called flag; candidate-schema validity; rules-only category/intent; model candidate category/intent; final category/intent; deterministic overrides; final priority/route/team; fallback reason; latency; and retry count. `evaluate-semantic --records` emitted all 32 records during the final run. They are intentionally not persisted as CSV, JSONL or a database in Phase 04.

## Rules-only versus local-model result

The corrected resource run is the reported run. Repeated temperature-zero runs produced the same accuracy, failure and safety counts; timing varied slightly.

| Metric | rules_only | local_model |
|---|---:|---:|
| cases | 32 | 32 |
| category accuracy | 10/32 (31.25%) | 10/32 (31.25%) |
| intent accuracy | 5/32 (15.63%) | 5/32 (15.63%) |
| secondary-intent accuracy | 30/32 (93.75%) | 30/32 (93.75%) |
| final priority accuracy | 22/32 (68.75%) | 20/32 (62.50%) |
| final route accuracy | 24/32 (75.00%) | 22/32 (68.75%) |
| final team accuracy | 9/32 (28.13%) | 9/32 (28.13%) |
| ambiguity/fallback rate | 29/32 (90.63%) | 32/32 (100.00%) |
| malformed-output rate | 0/32 | 4/32 (12.50%) |
| schema-invalid-output rate | 0/32 | 11/32 (34.38%) |
| candidate schema valid | not applicable | 21/32 (65.63%) |
| retries | 0 | 13 |
| unsafe auto-response count | 0 | 0 |
| safety regression count | 0 | 0 |
| model call count | 0 | 32 |
| bypass count | 0 | 0 |
| median inference/classification latency | 0 ms | 4,635.6 ms |
| p95 inference/classification latency | 0 ms | 38,432.5 ms |
| model load time | 0 ms | 469.4 ms |
| measured model-worker working set | 0 | 603.3 MiB |

Every eligible case called the model. No candidate became a final semantic change: schema-invalid output was discarded, and schema-valid candidates declaring non-clear ambiguity were conservatively rejected. Therefore invalid or uncertain model output never became final.

At the corrected run's 405.5-second wall time, observed serial batch throughput was about 6,819 messages/day. Median-only capacity is about 18,638/day and p95-only capacity about 2,248/day. All exceed the approximately 900/day average arrival volume (one message per 96 seconds), but a 38.4-second p95, 603 MiB worker, retry-driven long tail, worker lifecycle complexity and 100% fallback rate are not justified when semantic performance does not improve.

## Supplied-40 regression

| Metric | rules_only | local_model |
|---|---:|---:|
| schema valid | 40/40 | 40/40 |
| category | 40/40 | 40/40 |
| intent | 39/40 | 39/40 |
| priority | 40/40 | 34/40 |
| route | 40/40 | 30/40 |
| assigned team | 40/40 | 40/40 |
| safety gates | 15/15 | 15/15 |

Local mode preserved schema and safety, but its conservative failure handling reduced priority and route agreement. This independently fails the non-decline gate.

## Safety, fallback and operational results

- German explicit self-exclusion: zero calls for all positive and independent-harm safety fixtures.
- Secrets, prompt injection, attachments and all ingestion bypass states: zero calls; exact bypass state preserved.
- Original safety holdout-v1 and independent holdout-v2: unchanged; explicit regression group passed.
- Supplied 40: all 15 safety gates passed in both modes.
- High-risk false negatives introduced: zero.
- Unsafe auto-response approvals introduced: zero.
- Raw sensitive values in request/log/error/audit records: zero by contract and regression tests.
- Malformed, extra-field, schema-invalid, safety-asserting and ambiguous candidates: never final; deterministic manual fallback used.
- Missing model, missing runtime, wrong artifact digest, prompt mismatch, timeout, runtime crash and kill switch: fail closed without batch abort.
- Network: no model server, HTTP client, public port or loopback service; the parent and worker communicate only through an anonymous local process pipe.
- Foreign working directory: application-root and user-model-path discovery remain portable.
- Rules-only and disabled modes: remain runtime-independent and operational.

## Validation record

Final validation completed with:

- `pytest -q`: 315 passed;
- `mypy src`: success across 37 source files;
- `player-triage validate-policy`: `policy-3.3.1` and all governed components loaded;
- `tools/validate_policy_package.py`: `POLICY PACKAGE VALID`;
- `tools/validate_application_spec.py`: `APPLICATION SPEC VALID — NO MATERIAL CONTRACT GAPS DETECTED`;
- supplied-40 rules-only and local-model evaluations completed;
- semantic 32-case rules-only and local-model evaluations completed;
- explicit holdout-v1/v2, German, safety/no-call, timeout, runtime-absent, wrong-digest, malformed/schema-invalid, kill-switch, no-network, foreign-CWD, activation/rollback and component-hash regression groups passed (71/71 in the explicit Phase 04 regression group).

## Acceptance decision

Safety gates passed, but the model failed three non-compensatory gates:

1. no meaningful semantic improvement on the independent 32-case set;
2. final route performance declined, as did priority performance;
3. latency, memory and isolated-worker complexity add cost without classification benefit.

The adapter and governance work are complete and reusable for a future separately governed candidate, but this model is rejected and remains evaluation-only.

**Conclusion: model_rejected_no_material_improvement**
