# Phase 06 Report

## Objective completed

Implemented the rules-only evaluation, regression, non-compensatory safety,
change-impact, activation-gate, performance, capacity, cost-governance,
reliability, mutation and audit-reconstruction layer for `policy-3.3.1`.

This phase supports a controlled synthetic demonstration. It does not establish
production accuracy, production capacity, legal compliance or production
readiness from the supplied 40 messages.

Runtime state remained:

- mode: `rules_only`;
- effective model calls: 0;
- model conclusion: `model_rejected_no_material_improvement`;
- canonical supplied-run digest:
  `a90de550d29de67c053631d5937eff96ccd27be0d1f56e7843d3b4388f70a62b`.

## Opening Phase 05 contract verification and correction

The accepted Phase 05 run had a readable decision CSV, schema-valid audit JSONL,
SQLite run/decision/audit records, a manifest and the accepted canonical digest.
Its complete final decisions were embedded only in decision audit events, rather
than also being published in a distinct final-decision JSONL. Phase 06 corrected
that export boundary without changing a substantive decision.

Every new operational run now publishes:

- `decisions.csv`: readable operational view;
- `decisions.jsonl`: one `output_schema.json`-valid final decision per successful
  message;
- `audit_events.jsonl`: a separate stream containing only
  `audit_event_schema.json`-valid events;
- `audit.sqlite3`: approved run, decision, audit, evaluation and artifact-metadata
  records;
- `run_manifest.json`: relative artifact paths, record counts, digests,
  configuration provenance and canonical digest.

SQLite now has an `artifact_metadata` table with four rows for the CSV,
decision JSONL, audit JSONL and database. The database's own internal digest is
nullable to avoid a self-referential hash; its final digest is recorded in the
run manifest. Cross-artifact verification confirms that the final-decision JSONL,
decision audit snapshots and SQLite decisions agree exactly.

Final Phase 05 replay:

- run ID: `run-20260717T094500340Z-809304d70171`;
- input/success/failure: 40/40/0;
- bypass decisions: 9;
- model calls: 0;
- canonical digest: unchanged;
- `decisions.csv`: `17174eef01ccd65b73472cedb64aa095bfcfa81db045729030f8c54658fc08a6`;
- `decisions.jsonl`: `cc8ea52839bb60f4bde5b57daaafda8cd23701d0ebbe90c2a31b21da844e55e0`;
- `audit_events.jsonl`: `e36e3bd165441c648df5a7c602adf99c118f9d65923c302aaf8feeb1300b516f`;
- `audit.sqlite3`: `3e71013766eabdbae21ada96ae2f37b2b79a4b90e36d07bcb8f69b4d8b4c65bd`;
- `run_manifest.json`: `cf563ed017df3b34ca20f2bd51dd8d69c20f602abd894693e9d21448bf8cbca0`.

## Evaluation architecture and module boundaries

Phase 05's orchestration, exports and SQLite publication remain one transaction
coordinator because splitting that transaction would weaken failure isolation.
Reusable durable-write primitives were extracted to `artifact_io.py`.

Phase 06 is separated into public typed modules:

- `evaluation_datasets.py`: isolated dataset loading and rules-only execution;
- `evaluation_metrics.py`: exact/set metrics, confusion and safe error analysis;
- `evaluation_governance.py`: locked gates, baselines, change impact and activation;
- `evaluation_performance.py`: repeated benchmark, workload, capacity and cost;
- `evaluation_artifacts.py`: atomic machine-readable evidence publication;
- `evaluation_service.py`: public orchestration and audit reconstruction.

The CLI and a future UI call the public evaluation service. They do not need
private internals from the Phase 05 pipeline.

## Dataset separation

The following evidence sets remain separate; no combined headline accuracy is
reported:

1. `supplied-40`: synthetic demonstration set and accepted baseline;
2. `S01-S15`: non-compensatory safety assertions;
3. `holdout-v1`: preserved discovered-defect history and later regression set;
4. `holdout-v2`: independent safety holdout;
5. Phase 04 semantic holdout: historical evidence for model rejection only;
6. controlled Phase 06 mutation/fault probes: synthetic assurance evidence.

The Phase 04 v2 semantic holdout digest remains
`a21d02c1a4b965f6edbd5b72a5212aa074af4fb6492abfca9794df41d4d21273`.
It was verified but not combined with rules-only production-style metrics.

## Metrics and results

| Dataset | Messages | Category | Intent | Priority | Route | Assigned team | Schema/semantic valid | Core mismatches |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| supplied-40 | 40 | 40/40 | 39/40 | 40/40 | 40/40 | 40/40 | 40/40 | 1 |
| holdout-v1 | 25 | 22/25 | 21/25 | 25/25 | 25/25 | 22/25 | 25/25 | 10 |
| holdout-v2 | 18 | 18/18 | 18/18 | 18/18 | 18/18 | 18/18 | 18/18 | 0 |

Supplied-set category macro F1 is 1.0. All eight category labels have precision,
recall and F1 of 1.0 on this demonstration set. Critical-priority recall is 4/4.
Fallback and processing-failure rates are 0/40. Model bypass is 9/40 and manual
review is 30/40.

Additional supplied-set field results:

| Field | Agreement |
|---|---:|
| auto-response policy | 40/40 |
| auto-response template | 40/40 |
| human-review requirement | 40/40 |
| model eligibility | 40/40 |
| attachment/reference flags | 120/120 across three fields |
| linkage fields | 120/120 across three fields |
| secondary teams (exact set) | 27/40 |
| risk flags (exact set) | 9/40 |
| reason codes (exact set) | 32/40 |
| secondary-intent precision | 0.75 |
| secondary-intent recall | 0.273 |

The accepted deterministic baseline mismatch remains exactly:

- M22 `intent`: expected `withdrawal_delay`; actual
  `withdrawal_status_first_contact`.

This mismatch is neither modified nor hidden.

The new richer comparison also reports 52 supplied-set diagnostic differences
across secondary-team, risk-flag and reason-code sets. They are not silently
reclassified as the historical deterministic baseline, but they are fully
present in `mismatch_report.csv`, `mismatch_report.jsonl`, `dataset_results.json`
and the structured error analyses. These gaps materially limit claims about
secondary routing/provenance quality and must remain visible in Phase 07.

Holdout-v1 preserves its original first-run defect record. Current regression
results keep all 25 outputs schema/semantic valid, all four expected critical
cases critical, and the previously recorded secret, injection and negated
self-exclusion defects corrected. Its remaining ordinary core mismatches are
reported per message and are not merged into supplied-set metrics. Holdout-v2
has 18/18 exact core decisions, eight/eight critical cases recalled, and no
secret, injection or explicit-self-exclusion safety failure.

## Confusion and error analysis

Safe structured outputs contain no source message text or player identifier.
Each record uses only message/case ID, expected value, actual value, applicable
rule IDs, reason codes, dataset, and adjudication status.

Generated analyses cover:

- category confusion matrix;
- intent mismatch;
- priority under/over-escalation;
- route under/over-escalation;
- assigned/secondary-team mismatch;
- false auto-response approval;
- unnecessary specialist escalation;
- false-positive and false-negative safety detection.

## Non-compensatory safety gates

All official gates passed: S01-S15 = 15/15.

All additional locked assurance gates passed: 11/11. They cover independent
explicit-self-exclusion recall, harm/loss-of-control escalation, secret bypass,
prompt-injection bypass, critical-to-specialist routing, auto-response safety,
zero model calls, absence of autonomous action fields, transitional/prohibited
market overlay behavior, 100% output/audit schema and semantic validity, and
artifact safety scanning.

Combined result: 26/26 locked gates passed. Aggregate accuracy cannot compensate
for a gate failure; the evaluator exits non-zero if any locked gate fails.

Attachment bypass, redaction-uncertain fail-closed behavior and invalid-input
fail-closed behavior remain covered by the existing ingestion/model-gate tests
and the Phase 06 fault/mutation regression group. No account, payment, KYC,
self-exclusion, regulator or communication action is performed.

## Baseline and change-impact design

The accepted baseline is
`evaluation/baselines/supplied-40-policy-3.3.1.json`. It records policy and
application versions, dataset version/digest, canonical decision digest,
expected metrics, gate outcomes, approved mismatch, timestamp, owner/reviewer
and status.

Baseline comparison passed:

- dataset digest unchanged;
- canonical digest unchanged;
- no introduced or resolved approved mismatch;
- no safety-gate change.

The active-versus-candidate comparison runs both configurations against the same
frozen datasets without activating the candidate. Its structured diff includes
field-level decision changes, priority increases/decreases, route/team changes,
auto-response and bypass changes, newly invalid outputs, resolved mismatches and
introduced mismatches. The final self-comparison has zero changes.

## Locked activation gates

A candidate is blocked for any official or derived safety failure, explicit
self-exclusion weakening, secret/injection model eligibility, critical route
weakening, unsafe auto-response, output/audit validity below 100%, forbidden
artifact data, configuration hash failure, rollback failure or newly invalid
output.

The unchanged active configuration is `eligible_for_controlled_review`; this is
not automatic activation and not a production-readiness statement. Quality
thresholds remain guarded while safety thresholds are locked.

## Performance benchmark

The benchmark used one warm-up and five measured complete 40-message runs. Each
run included ingestion, classification, CSV/decision/audit export, SQLite,
manifest and verification. Optional model initialization, network access and
test instrumentation were absent. Python bytecode/first-run effects were
excluded by warm-up. Antivirus impact was not independently measurable.

Host profile is recorded in `performance_results.json`.

| Measurement | Result |
|---|---:|
| median application/configuration startup | 1,239.3 ms |
| median input loading | 23 ms |
| median 40-message processing stage | 346 ms |
| median decision/audit export | 700 ms |
| median SQLite write | 202 ms |
| median verification | 496 ms |
| median complete pipeline | 1,788 ms |
| measured throughput | 22.37 messages/s |
| per-message classification median | 4 ms |
| per-message classification p95 | 4 ms |
| approximate peak Python allocations | 2,754,621 bytes |

The memory number is `tracemalloc` Python allocation peak, not total process
working set.

Measured artifact sizes for 40 decisions:

- CSV: 16,211 bytes;
- decision JSONL: 49,955 bytes;
- audit JSONL: 92,793 bytes;
- SQLite: 331,776 bytes;
- manifest: 3,352 bytes.

## Capacity assessment for approximately 900 messages/day

At measured serial throughput:

- estimated rules-only compute time: 40.23 seconds/day;
- required steady throughput over 24 hours: 0.0104 messages/s;
- required throughput over eight hours: 0.03125 messages/s;
- illustrative 10x business-hour burst: 0.3125 messages/s;
- full-day replay estimate: 40.23 seconds;
- recommended batch size: 100;
- recommended concurrency: 1 to preserve deterministic ordering.

Scaled artifact storage is approximately 11,116,935 bytes per 900-message day
and 4,057,681,275 bytes for 365 days, plus an illustrative 614,400 bytes/year
for configuration archives. This is linear extrapolation from local files, not
a production endurance, concurrency, backup or restore test.

## Human-review workload estimate

Supplied-set route counts:

- auto-response: 10;
- human agent: 16;
- specialist: 14.

Priority counts are 12 low, 15 medium, nine high and four critical. The set has
nine bypass decisions, zero cases with recorded missing context and one repeat
contact. Complete counts by assigned team and market are in
`human_review_workload.json`.

Illustrative scaling to 900/day gives 225 auto-responses, 360 human-agent cases,
315 specialist cases, 202.5 bypasses and 22.5 repeat contacts. This extrapolation
from 40 supplied messages is not statistically representative.

## Cost governance

The formula inputs are configurable examples: EUR 0.20/kWh, estimated 65 W local
process power, EUR 0.03/GB-month storage, six minutes per human-agent case,
15 minutes per specialist case and EUR 22/hour illustrative labor.

Under those assumptions:

- local prototype compute energy: approximately EUR 0.00015/day;
- one-year artifact storage: approximately EUR 0.11/month;
- illustrative review workload: 114.75 hours/day and EUR 2,524.50/day.

The review estimate is the dominant modeled cost and demonstrates why the
supplied route mix must not be treated as representative production staffing.
Production infrastructure is not sized; availability, backups, monitoring,
security, deployment, identity/RBAC and restore validation remain cost drivers.

The local model is historical/rejected and is not recommended. No hosted
provider is selected. A hosted API is not part of the architecture, no hosted
rate is committed, and OpenAI public policy currently prevents this real-money-
gambling use without explicit authorization.

## Reliability and fault injection

The complete regression suite verifies malformed/missing/duplicate input,
unsupported values, configuration and schema failures, hash mismatches, output
unavailability, write/rename failures, SQLite rollback, manifest/artifact digest
tampering, safe temporary cleanup, prior-run preservation, isolated processing
failure, no-network operation, foreign-CWD execution and optional-runtime absence.

Failure behavior is fail-closed and sanitized. A completed run is never
overwritten. Hidden incomplete temporary directories are never interpreted as a
successful run; restart creates a new unique run identity. No final-looking
partial evaluation artifact survives a failed atomic rename.

## Mutation testing

Six locked simulations were executed without activation:

- weaken explicit self-exclusion;
- remove sensitive-secret bypass;
- weaken prompt-injection bypass;
- lower a safety-critical priority;
- change critical specialist routing to human;
- enable a guarded auto-response.

Every unsafe simulation was blocked by candidate invariants. Market Compliance
overlay removal is also locked. Repeat-contact and small-balance threshold
changes remain guarded/editable respectively, but require a complete versioned
impact diff and regression run. No mutation was activated.

## Audit reconstruction

Reconstruction passed for M07, M11, M18, M23, M31 and M38. For each case the
test reconciles final decision JSONL, the decision audit snapshot and SQLite,
and verifies decision path, rule-list field, reason codes, component provenance,
market overlay, linkage and policy-basis fields.

Run-level reconstruction verifies input digest, application version, policy
version, component digests and canonical digest. It does not require raw
sensitive content, model chain-of-thought, an undocumented Python branch or
mutable current state.

## Evaluation artifacts and digests

All generated files are under `output/`; the complete mapping is recorded in
`output/evaluation_manifest.json`.

| Artifact | SHA-256 |
|---|---|
| `evaluation_summary.json` | `ad8795f1cbcc5435b9d14b9dbd9ead5d84534cd68c4f8fc6115f7006aa4767b1` |
| `mismatch_report.jsonl` | `2a9441a6cdcd34456d201f9e21e688b000603558e6bac024b7d8c2dd185a0632` |
| `mismatch_report.csv` | `4b1f88f7dc3642206a1e47593e456150832aff3dfe2e9ccdea4eacf23f0661de` |
| `confusion_matrix.csv` | `f1677e75c6e6b813bba8eceefd3e9671c5273a8c2c6b6e6a73ec7dac0b9dce30` |
| `safety_gate_results.json` | `00db6b166d387976630e29c34c444002137ab215829b564aca89102f7bd21984` |
| `performance_results.json` | `624a43e3a415ad4278190366f3d5f3b3c09afeea40ef05c333d90cb1920f3f75` |
| `capacity_estimate.json` | `ad29a3fcf6255d82f7b82342a084927a60e253a391b7e21208493522f8e6ed50` |
| `change_impact.json` | `b1de89a3f2327cf026fdbe38a5e706636c60d07c3976d378374ac0431650104a` |
| `activation_recommendation.json` | `78b9c0f3070f849b692be68607d96ddcd9016b169319d80f912115b55a3bbc0a` |
| `dataset_results.json` | `d561c4f9c137ed2ee4f452c580f745a043d692a0d83b598fb897d66be4eac9c4` |
| `cost_assumptions.json` | `5d260b76d898459c7e08026d318b0b152e103bacd21f598c126e6722a3fc91e6` |
| `cost_estimate.json` | `da06bb157930c49bd381054ba7c90fb652c8a92484e0f190a9fb290fba9c8d50` |
| `human_review_workload.json` | `ac2cdd52be347e417f8ed8f836c07b8097bf91eb00f90c904bfa7de65778009c` |
| `baseline_comparison.json` | `eab06afd29d814ade66629a61dbba8dfda9f7704ad6d9b996d7686cabbc5a212` |
| `audit_reconstruction.json` | `ab47e0e8fd54e57816aa7a0ffe7536abacfd87378e1c36e05cc573984a596d27` |
| `semantic_holdout_history.json` | `0f5b56c938f9ecfbabcabaff7d52df47785404241e009ecab8e88e732f091947` |
| `reliability_results.json` | `88bcf6848c90ca922f68809093ffcd6bd69458daac7290a9b37decdf3ad2edbe` |
| `mutation_results.json` | `c7f4fc15c8df6ca5129b7e97fa54cf1150230c6f0a3a7570902c818e0a7f9e44` |

Generated outputs are intentionally ignored by Git; schemas, code, baseline and
this report are tracked.

## Validation record

Commands executed:

```text
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m mypy src
.venv/Scripts/player-triage.exe validate-policy
.venv/Scripts/python.exe tools/validate_policy_package.py
.venv/Scripts/python.exe tools/validate_application_spec.py
.venv/Scripts/player-triage.exe run --mode rules_only
.venv/Scripts/player-triage.exe evaluate --mode rules_only --performance
```

Results:

- complete suite: 344 passed;
- mypy: success across 45 source files;
- policy CLI: active `policy-3.3.1` loaded;
- policy package: valid;
- application specification: valid with no material contract gaps;
- Phase 05 replay: 40/40 decisions, 15/15 official gates, zero model calls;
- supplied, holdout-v1 and holdout-v2 evaluations: completed separately;
- semantic-holdout history: digest verified;
- locked safety gates: 26/26;
- baseline/deterministic replay: canonical digest unchanged;
- mutation, fault-injection, audit reconstruction, no-network,
  foreign-CWD and optional-runtime-absent coverage: passed.

## Files added or changed

- Added `evaluation/baselines/supplied-40-policy-3.3.1.json`.
- Added `artifact_io.py` and seven typed Phase 06 evaluation modules.
- Added `tests/test_phase06_evaluation.py` and expanded Phase 05 export tests.
- Updated the operational export/manifest/SQLite contract and CLI.
- Updated the application export and SQLite documentation.
- Added this Phase 06 report.

No policy component, controlled vocabulary, safety assertion, ground truth or
schema was modified.

## Known limitations

- The supplied 40 are a demonstration set, not a statistically representative
  sample.
- The 52 set-valued diagnostic differences and low secondary-intent recall limit
  secondary routing/provenance claims even though core fields and safety gates
  pass.
- Holdout-v1 retains ordinary semantic/team mismatches; the corrected historical
  safety defects remain fixed.
- Performance is a local serial benchmark, not a production load, endurance,
  failover or restore test.
- Python allocation peak is not total process memory.
- Storage, energy and staffing figures are formula-driven illustrations.
- Enterprise authorization, RBAC, immutable external audit storage, monitoring,
  backup/restore, deployment and production data governance remain absent.

## Recommendation for Phase 07

Phase 07 may proceed only when explicitly authorized. Its UI should consume the
public Phase 06 service and sanitized artifacts, keep candidate activation behind
the locked gates, show the M22 baseline and 52 diagnostic set differences, and
preserve rules-only/no-network operation.

This recommendation is readiness for controlled UI-based changes in the
synthetic demonstration, not production readiness.

## Stop statement

Phase 06 is complete. Streamlit, Policy Studio, Phase 07, n8n and all external
integrations were not started.
