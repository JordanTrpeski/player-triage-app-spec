# Configuration Versions and Provenance

**Active bundle: `policy-3.3.1`.** Each version is archived under
`policy/config_versions/<version>/` for activation/rollback.

| Version | Parent | Summary | Status |
| --- | --- | --- | --- |
| policy-3.0.0 | policy-2.0 | Frozen Stage-9 policy contract (7 components) | historical (rollback target) |
| policy-3.1.0 | policy-3.0.0 | Added `derived_refinement_rules` as a versioned, hash-verified policy component | historical |
| policy-3.2.0 | policy-3.1.0 | Detector hardening: AUTH_SECRET value-bearing detection, prompt-injection families, self-exclusion negation guards | historical |
| policy-3.3.0 | policy-3.2.0 | Phase 04 multilingual safety candidate | **superseded — failure preserved** (`tests/data/phase04_policy_3_3_0_failure.md`) |
| **policy-3.3.1** | policy-3.3.0 | Corrected German self-exclusion activation phrasings + matching negation/informational/attributed/quoted guards | **active / accepted** |

## Component digests (active `policy-3.3.1`)
Recorded in `policy/configuration_manifest.json` and re-emitted per run in
`outputs/run_manifest.json → configuration_component_digests`. Twelve components
are versioned; the hash-locked policy set plus `derived_refinement_rules`,
`model_configuration`, `research_traceability` and `ui_editability`.

## Runtime / model status (accepted)
- **Runtime mode:** `rules_only`.
- **Final run:** `model_enabled = false`, `model_called = false`
  (`outputs/run_manifest.json`).
- **Model conclusion:** `model_rejected_no_material_improvement`
  (`model_approval_status = rejected`).
- **`policy/model_configuration.json`** records the *evaluated* model
  (Qwen2.5-0.5B-Instruct GGUF q4_k_m, apache-2.0, pinned revision + SHA-256,
  prompt version/digest, deterministic generation settings). Its
  `approval_status = evaluation_only` and `enabled` flag scope the **Phase 04
  evaluation harness** (`evaluate-semantic`) only; they do **not** enable the model
  in the production `run` pipeline, which is `rules_only`. Model weights are stored
  outside the repository and are not packaged.

## Rollback evidence
Rollback to any archived version restores that version's components and digests
atomically, requires the literal `ROLLBACK` confirmation, and is audited. The
Phase 07 walkthrough demonstrated draft → validate → impact → activate → rollback
and restored the active version to `policy-3.3.1`; see
`docs/phase_reports/phase_07.md` and `tests/test_phase07_console.py`.

## Canonical decision digest
`a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b` — the
order-independent SHA-256 over the 40 final decisions under `policy-3.3.1`,
rules-only. Verified in the final run (`outputs/run_manifest.json`).
