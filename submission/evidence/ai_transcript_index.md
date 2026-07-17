# AI-Development Transcript Index

This project was built with AI coding assistants. Raw conversation transcripts are
**not committed** (they may contain incidental host/session data); this index makes
the development process auditable without them, and every phase is backed by a
committed phase report, tests and validators. AI output was **not** accepted
unchanged — corrections are noted below.

| Work | Assistant(s) | Purpose | Produced / evidence | Reviewed / validated | Notable corrections |
| --- | --- | --- | --- | --- | --- |
| Policy synthesis (Stage 9) | Prior research (pre-repo) | Frozen policy contract, taxonomy, safety assertions, vocab | `policy/*.json`, `policy/*.md`, `schemas/*.json` | Validated by `tools/validate_policy_package.py` + `validate_application_spec.py` | Treated as immutable input; hashes locked |
| Phase 00 audit | Claude Code | Verify frozen bundle + validators | `docs/phase_reports/phase_00.md` | Both validators pass | Fixed CRLF-corrupted line endings on Windows clone (broke component hashes) |
| Phase 01–02 | Claude Code | Scaffold, typed config, ingestion/redaction/detection/linkage | `src/player_triage/{config,ingestion,detection,redaction,linkage,...}.py` | 125 tests; validators pass | — |
| Phase 03 / 03B | Claude Code (Opus 4.8) | Deterministic engine, baseline, derived rules, final policy, validation | `src/player_triage/{engine,baseline_classifier,rule_engine,final_policy,derived_rules,validation,decision,evaluation}.py` | 198 tests; 15/15 gates | Placed derived rules as data-driven config, not Python branches; no message-id conditions |
| Phase 03C governance | Claude Code | Promote derived rules to a versioned/hash-verified policy component | `policy/derived_refinement_rules.json`, `schemas/derived_refinement_rules_schema.json`, manifest `policy-3.1.0` | Governance + rollback tests | Manifest-declared optional component; true rollback |
| Phase 03D detector hardening | Claude Code | AUTH_SECRET value-bearing detection, injection families, negation guards | `policy/{redaction_policy,policy_rules,baseline_intent_rules}.json`, manifest `policy-3.2.0` | 258 tests; holdout-v2 18/18 | Root cause of holdout FNs was engine fallback dropping bypass — fixed in `engine.py`; patterns kept in config |
| Phase 04 model feasibility + adapter | Codex (same machine) | Local-model adapter, gate, governance, benchmark | `src/player_triage/model/*`, `policy/model_configuration.json`, `schemas/model_configuration_schema.json`, `docs/phase_reports/phase_04.md` | No-call safety tests; schema-strict validation | Model **rejected** (`model_rejected_no_material_improvement`); weights kept outside the repo |
| Phase 04 multilingual safety remediation | Codex | German self-exclusion + guards before model eval | `policy/policy_rules.json`, manifest `policy-3.3.0` → accepted `policy-3.3.1` | German self-exclusion fixtures + gates | policy-3.3.0 candidate failure preserved (`tests/data/phase04_policy_3_3_0_failure.md`); corrected in 3.3.1 |
| Phase 05 operational pipeline | Codex | Rules-only run + verified CSV/JSONL/SQLite/audit + run manifest | `src/player_triage/operational.py`, `artifact_io.py`, `docs/phase_reports/phase_05.md` | Canonical decision digest `a90de550...` | — |
| Phase 06 evaluation service | Codex | Metrics, gates, holdouts, performance, capacity, governance | `src/player_triage/evaluation_*.py`, `docs/phase_reports/phase_06.md` | 15/15 gates, 26/26 locked | Demonstration vs synthetic kept separate |
| Phase 07 operator console | Codex | Local Streamlit console + governed config lifecycle | `src/player_triage/{console_service,configuration_manager,pattern_lab,ui/*}.py`, `docs/phase_reports/phase_07.md` | `tests/test_phase07_console.py` | localhost-only; model editing not exposed via normal UI |
| Phase 08 packaging | Claude Code | Submission package, docs, manifest, ZIP, final validation | `submission/*`, `docs/phase_reports/phase_08.md` | Final test/validator/digest battery | — |

**Provenance of factual claims:** metrics come from committed artifacts
(`submission/evaluation/*`, `submission/outputs/run_manifest.json`) and the phase
reports, not from unverified assistant assertions. Policy traceability lives in
`policy/research_traceability.json`. No transcripts were fabricated; where a raw
transcript is unavailable it is stated as such.
