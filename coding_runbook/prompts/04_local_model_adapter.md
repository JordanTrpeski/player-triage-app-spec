# Phase 04 — Optional Local Model Adapter and Feasibility Spike

Prerequisite: Phase 03 passes in rules-only mode.

Read:
- `policy/model_contract.md`
- `policy/classifier_prompt.txt`
- `schemas/model_candidate_schema.json`
- `policy/controlled_vocabularies.json`
- `coding_runbook/agent_operating_rules.md`

First perform a local feasibility report:
- Detect OS, CPU, RAM and available GPU/VRAM without exposing unrelated host data.
- Identify at most two locally runnable instruction models with permissive/commercially usable licences and safe serialization.
- Record official repository, immutable revision, licence, download size, RAM/VRAM estimate and runtime.
- Prefer an in-process or loopback-only runtime; no public service port.
- Do not use OpenAI or any hosted LLM API.

Implement the provider interface:
- `RulesOnlyProvider`
- `MockProvider` for invalid schema, timeout and outage tests
- `LocalModelProvider` only if a candidate installs reliably in the environment

The local model receives only redacted eligible text and returns the model-candidate schema. The deterministic policy engine remains authoritative.

Required safety:
- No tools, browsing, retrieval, files or external calls.
- No prompt/output logging.
- Temperature 0 or closest deterministic setting.
- Strict schema validation and one bounded retry.
- Timeout and circuit-breaker/fallback hooks.
- Model unavailable must not break rules-only operation.

Benchmark on eligible cases only: latency, output validity, category/intent agreement and multilingual M22/M23 behavior. M23 should still bypass the model.

Write `docs/phase_reports/phase_04.md`, including whether local-model mode is enabled or deferred, and stop.
