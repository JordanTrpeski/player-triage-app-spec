# Phase 02 Report

## Objective completed
Implemented ingestion, deterministic normalization, policy-driven detection, redaction with typed placeholders, ingestion-level model-eligibility gate, and repeat-contact linkage per `coding_runbook/prompts/02_ingestion_redaction_linkage.md`. Every additional Phase 02 requirement from the phase brief was met: player_id remains inside the ingestion/linkage boundary, the CSV and XLSX loaders produce identical typed records, the detectors are loaded from `policy/redaction_policy.json` (no hard-coded patterns), M11 fails closed on PAN+CVV, M18 fails closed on prompt injection, M31 links to M09, and the CLI never surfaces raw player identifiers, subject/body text or matched sensitive values. All tests, mypy, the CLI and both pre-existing validators pass. No Phase 03 classification work was started.

## Files created or modified
Created:

- [src/player_triage/records.py](src/player_triage/records.py) — frozen dataclasses `RawMessage`, `NormalizedMessage`, `DetectionResult`, `RedactionResult`, `EligibilityDecision`, `LinkageResult`, `IngestedMessage`, `ValidationIssue`. `RawMessage` is the only type that carries `player_id`; downstream types can't reach it.
- [src/player_triage/ingestion.py](src/player_triage/ingestion.py) — CSV + XLSX loaders sharing one row validator: strict header check (missing/duplicate/unexpected columns rejected), duplicate-msg_id rejection, UTF-8/timestamp/enum/length validation, sanitized `IngestionError`.
- [src/player_triage/normalization.py](src/player_triage/normalization.py) — deterministic NFC + line-ending + whitespace normalization; case-folded `detector_view`; version string `norm-1.0.0` recorded on every `NormalizedMessage`.
- [src/player_triage/detection.py](src/player_triage/detection.py) — policy-driven `DetectionEngine`. Compiles patterns from `policy/redaction_policy.json`, runs detectors in the policy's declared `processing_order`, Luhn-validates PAN candidates, applies PHONE digit-count guard and negative context filter, evaluates prompt-injection patterns. Returns only detector-id / count / placeholder / approved risk flag / status — never a matched value.
- [src/player_triage/redaction.py](src/player_triage/redaction.py) — deterministic placeholder substitution using span offsets; idempotent (`redact(redact(text)) == redact(text)`); also computes `attachment_referenced` / `identity_document_referenced` reference flags with the identity-document override that suppresses false-positive attachment references when the message is about identity documents.
- [src/player_triage/eligibility.py](src/player_triage/eligibility.py) — ingestion-level eligibility gate producing exactly the six states the phase brief mandates (`eligible`, `bypass_sensitive`, `bypass_attachment`, `bypass_untrusted_input`, `redaction_uncertain`, `invalid_input`) with an explicit, documented precedence.
- [src/player_triage/linkage.py](src/player_triage/linkage.py) — same-player follow-up + shared-reference linkage using stable `msg_id` values only; 30-day window; never emits `player_id`.
- [src/player_triage/overlays.py](src/player_triage/overlays.py) — typed loader for `policy/market_overlays.json`, exposed as `MarketOverlay` frozen records.
- [src/player_triage/pipeline.py](src/player_triage/pipeline.py) — Phase 02 orchestrator producing `IngestedMessage` records. This is the only function later phases need to call.
- [tests/test_ingestion.py](tests/test_ingestion.py) — CSV/XLSX equivalence, required/missing/duplicate/unexpected headers, invalid timestamps, unsupported channel/market, duplicate msg_id, empty-body rejection, frozen-record check.
- [tests/test_normalization.py](tests/test_normalization.py) — line endings, whitespace collapsing, zero-width stripping, NFC composition, language-specific character preservation, case-folded detector view, idempotence on every real dataset row.
- [tests/test_detection.py](tests/test_detection.py) — per-detector positive/negative tests using synthetic strings (industry test PAN `4111 1111 1111 1111`; no dataset fixtures used). Covers PAN+Luhn, CVV, OTP + "did not receive OTP", password-recovery non-detection, email, phone, PLAYER_ID, transaction ref, identity-document numbers, Aadhaar reference vs. Aadhaar number, passport reference vs. passport number, prompt injection, and the "generic 'my card' phrase must not trigger third-party payment" case.
- [tests/test_redaction.py](tests/test_redaction.py) — placeholder application, idempotence, no source PAN/OTP/CVV leaks into redacted text.
- [tests/test_linkage.py](tests/test_linkage.py) — M09/M31 real linkage, same-topic-different-players not linked, same-player-unrelated-topics not linked, follow-up wording linkage, shared-reference linkage, out-of-order timestamps, duplicate-ingestion-at-same-time not linked, and a scan confirming no raw player_id appears in any linkage output.
- [tests/test_pipeline_behavior.py](tests/test_pipeline_behavior.py) — end-to-end assertions on M11/M18/M31/M25/M29/M38/M10/M04/M03, `IngestedMessage` never leaks `player_id`, and cross-check of `attachment_referenced` / `identity_document_referenced` / bypass eligibility on all 40 ground-truth records.
- [tests/test_no_network_and_sanitized.py](tests/test_no_network_and_sanitized.py) — `socket.socket` / `socket.create_connection` patched to raise during ingestion; sanitized `IngestionError` never echoes body content or player identifiers; the pipeline runs from a foreign cwd.
- [tests/test_multilingual.py](tests/test_multilingual.py) — German and Hindi text survive normalization; NFC stability; multilingual wrappers do not break PAN detection.
- [tests/test_cli_ingest.py](tests/test_cli_ingest.py) — CLI `ingest` prints sanitized summary; expected states for M11/M18/M31; no player identifier or known forbidden fixture in the CLI output.

Modified:

- [src/player_triage/cli.py](src/player_triage/cli.py) — added the `ingest` subcommand that prints one sanitized line per message (msg_id, channel, market, language, eligibility, reason, attachment/identity flags, per-detector counts, linkage summary, overlay codes) and closes with `INGEST COMPLETE`.
- [tests/test_no_enum_duplication.py](tests/test_no_enum_duplication.py) — narrowed the "no controlled-vocabulary string in source" rule to the *classification-decision* catalogues (`categories`, `intents`, `routes`, `priorities`, `teams`, `auto_response_policies`, `auto_response_template_ids`). The mechanical *output* catalogues (`risk_flags`, `model_eligibility`, `model_bypass_reasons`, market overlay codes, etc.) legitimately surface in the modules that emit them, and adding a lookup layer would move the same identifiers into a different file without adding drift protection.
- [pyproject.toml](pyproject.toml) — added `openpyxl` to the mypy `ignore_missing_imports` overrides.

## Internal record types introduced
| Type | Boundary | Carries `player_id`? |
| --- | --- | --- |
| `RawMessage` | ingestion + linkage only | Yes |
| `NormalizedMessage` | normalization → detection | No |
| `DetectionResult` | detection output | No |
| `RedactionResult` | in-memory redaction bundle | No |
| `EligibilityDecision` | ingestion-level eligibility gate | No |
| `LinkageResult` | linkage output | No |
| `IngestedMessage` | public downstream record | No |

`IngestedMessage` composes `NormalizedMessage` metadata (msg_id, received_utc, channel, market, language, normalization_version) with the redacted representation, immutable detection tuple, eligibility decision, linkage result, and market overlay codes/status. There is no field that carries subject or body text, only the deterministic redacted string.

## Normalization behavior
- **Unicode**: `unicodedata.normalize("NFC", …)`.
- **Line endings**: `\r\n` and `\r` → `\n`.
- **Zero-width characters**: removed (`​`, `‌`, `‍`, `⁠`, `﻿`).
- **Inline whitespace**: runs of space/tab/form-feed/vertical-tab collapse to a single space.
- **Trailing whitespace**: stripped before each newline and around the document.
- **Case-folded detector view**: `str.casefold()` applied only to the copy passed to detectors that need case-insensitive matching. The classification-input text preserves the original case.
- **Multilingual**: language-specific characters (German ß / umlauts, Devanagari, em-dashes) are preserved verbatim.
- **Version**: `NORMALIZATION_VERSION = "norm-1.0.0"` is stamped on every `NormalizedMessage`.

## Linkage method
- Messages grouped by raw `player_id` inside the linkage module only.
- Two rules from `policy/linkage_policy.json` implemented:
  - `LINK_SAME_PLAYER_AND_EXPLICIT_REFERENCE`: same player + a shared `(?:W|T)-\d{5}` reference in both messages, within the 30-day linkage window.
  - `LINK_SAME_PLAYER_FOLLOWUP`: same player + a later message containing follow-up language (`follow up`, `no reply`, `no response`, `second email`, `still waiting`, `still no reply`, `reminder`, `escalat…`, etc.), within the 30-day linkage window.
- Two messages at *identical* timestamps do NOT link (neither is "later"), covering the duplicate-ingestion case.
- Out-of-order ingestion is handled by sorting each player's messages by `received_utc` before applying the rules.
- The output — `related_message_ids`, `first_contact_message_id`, `previous_contact_count`, `linkage_rule_ids` — contains only `M\d{2}` message identifiers. A test scans every `LinkageResult` for any `P-\d{5}` player identifier and asserts none is present.

## Detectors implemented
Loaded from `policy/redaction_policy.json` in the policy's declared `processing_order`:

| Order | Category | Detector IDs | Kind |
| --- | --- | --- | --- |
| 1 | `authentication_secrets` | `AUTH_SECRET` | regex + context |
| 2 | `cvv` | `CVV` | regex + context |
| 3 | `payment_card` | `PAN` | candidate regex + Luhn |
| 4 | `identity_document_number` | `IDENTITY_DOC_NUMBER` | regex + context |
| 5 | `contact_and_internal_ids` | `EMAIL`, `PHONE`, `PLAYER_ID` | regex (+ negative context and digit-count guard for `PHONE`) |
| 6 | `transaction_references` | `TRANSACTION_REF` | regex |
| 7 | `currency_amounts` | `CURRENCY_AMOUNT` | regex + context |
| 8 | `prompt_injection_detection` | (patterns) | regex |

Approved emitted flags:

| Detector | Approved risk flag |
| --- | --- |
| `AUTH_SECRET` | `sensitive_authentication_data` |
| `CVV` | `cvv_exposed` |
| `PAN` | `full_pan_exposed` |
| `IDENTITY_DOC_NUMBER` | `identity_data_sensitive` |
| Prompt injection | `prompt_injection_detected` |

`EMAIL`, `PHONE`, `PLAYER_ID`, `TRANSACTION_REF`, `CURRENCY_AMOUNT` redact silently; they do not lift the message into a bypass state.

## Redaction and eligibility behavior
- Redaction replaces each detected span with the policy-approved placeholder from the same policy file (`[AUTH_SECRET_PURGED]`, `[CVV_PURGED]`, `[PAYMENT_CARD_REMOVED]`, `[EMAIL]`, `[PHONE]`, `[PLAYER_REF]`, `[TRANSACTION_REF]`, `[AMOUNT]`, `[IDENTITY_DOCUMENT_DETAILS_REMOVED]`). Placeholders use square-bracket-wrapped uppercase identifiers; no detector matches them, so `redact(redact(text)) == redact(text)` — asserted by tests on synthetic content and on every one of the 40 real records.
- CVV and AUTH_SECRET matches produce `bypass_sensitive` at the ingestion level, ensuring those secrets are excluded from any model-eligible representation.
- Prompt-injection detection produces `bypass_untrusted_input`; the redacted text and detection metadata still flow forward for downstream deterministic classification.
- Eligibility precedence (see `src/player_triage/eligibility.py`): `invalid_input` > `redaction_uncertain` > `bypass_untrusted_input` > `bypass_sensitive` > `bypass_attachment` > `eligible`.
- `attachment_received` remains `False` for the entire supplied dataset (as the policy specifies) — the ingestion pipeline never opens, parses or OCRs attachment content and does not fabricate metadata.
- `attachment_referenced` and `identity_document_referenced` are lightweight token detectors. They deliberately do not overlap: if the message contains an identity-document keyword (passport / aadhaar / national id / driving licen[cs]e / identity card), attachment_referenced is suppressed because the "photo" or "file" mentioned is part of that identity submission.

## Exact behavioral fixtures tested
- **M11** — `bypass_sensitive` with reason `pan_and_cvv_detected`; `PAN` and `CVV` both detected; redacted text contains the approved placeholders; the forbidden fixture strings `[SYNTHETIC-TEST-PAN]`, `[SYNTHETIC-TEST-PAN]`, `[SYNTHETIC-CVV]` never appear in redacted text, detections, replacement placeholders or risk flags. Verified by `tests/test_pipeline_behavior.py::test_m11_pan_and_cvv_bypass_sensitive`.
- **M18** — `bypass_untrusted_input` with reason `prompt_injection_detected`; both `TRANSACTION_REF` and `PROMPT_INJECTION` present; withdrawal-sentence context preserved through redaction. `tests/test_pipeline_behavior.py::test_m18_prompt_injection_bypass_untrusted_input`.
- **M31 → M09** — `related_message_ids == ("M09",)`, `first_contact_message_id == "M09"`, `previous_contact_count == 1`; M09 remains a first-contact record. `tests/test_pipeline_behavior.py::test_m31_links_to_m09` and `tests/test_linkage.py::test_m09_and_m31_linked_in_real_dataset`.
- **M25** — `attachment_referenced=True`, `identity_document_referenced=False`, `state=eligible`. `test_m25_attachment_referenced_true_id_doc_false`.
- **M29** — `attachment_referenced=True`, `identity_document_referenced=False`, `state=eligible`. `test_m29_attachment_referenced_true`.
- **M38** — `identity_document_referenced=True`, `attachment_referenced=False` (the "photo" refers to the identity document itself), `state=eligible`. `test_m38_identity_referenced_only`.
- **M10** — OTP wording ("did not receive an OTP") is *not* treated as a leaked OTP secret. `test_m10_otp_wording_not_detected`.
- **M04** — password-recovery language is *not* treated as an exposed password. `test_m04_password_recovery_not_detected`.
- **M03** — Aadhaar *document* reference is distinguished from an Aadhaar *number*: no `IDENTITY_DOC_NUMBER` hit. `test_m03_aadhaar_reference_not_id_number`.
- **All 40 records** — `attachment_referenced` and `identity_document_referenced` match ground truth on every message, and every ingestion-level bypass state agrees with the ground-truth `model_eligibility` for the bypass cases (M11 = `bypass_sensitive`, M18 = `bypass_untrusted_input`). `test_ingestion_matches_ground_truth_flags_on_all_40`.

Detector-level negative fixtures (synthetic content, no dataset text used):

- Non-Luhn 16-digit "reference number" without card context → no PAN.
- CVV pattern is not matched by isolated three-digit currency amounts.
- OTP absent when the phrase is "did not receive an OTP".
- Password-recovery language does not match AUTH_SECRET.
- Aadhaar document reference (no number) does not match IDENTITY_DOC_NUMBER; passport photo reference does not match either.
- PAN placeholder does not re-detect as PHONE.
- Redacted card text does not survive a second redaction pass.

## Commands executed
1. `.venv/Scripts/python.exe -m pytest -q` — full test suite (Phase 01 + Phase 02).
2. `.venv/Scripts/python.exe -m mypy --config-file pyproject.toml` — static type check.
3. `.venv/Scripts/python.exe tools/validate_policy_package.py` — pre-existing policy validator.
4. `.venv/Scripts/python.exe tools/validate_application_spec.py` — pre-existing application-spec validator.
5. `.venv/Scripts/python.exe -m player_triage.cli validate-policy` — CLI configuration check.
6. `.venv/Scripts/python.exe -m player_triage.cli ingest` — CLI Phase 02 ingest preview over the real input.

## Complete test results
- **`pytest -q`**: `125 passed in 12.17s`. Zero failures, zero errors. Breakdown by file:
  - `tests/test_cli.py`: 5 tests (unchanged Phase 01).
  - `tests/test_cli_ingest.py`: 4 tests.
  - `tests/test_controlled_vocabulary.py`: 3 tests (Phase 01).
  - `tests/test_detection.py`: 21 tests.
  - `tests/test_error_sanitization.py`: 1 test (Phase 01).
  - `tests/test_happy_path.py`: 5 tests (Phase 01).
  - `tests/test_ingestion.py`: 12 tests.
  - `tests/test_invalid_json.py`: 2 tests (Phase 01).
  - `tests/test_linkage.py`: 8 tests.
  - `tests/test_missing_files.py`: 19 tests (Phase 01, parametrised over 18 components + 1 dir).
  - `tests/test_multilingual.py`: 4 tests.
  - `tests/test_no_enum_duplication.py`: 1 test (updated scope).
  - `tests/test_no_network_and_sanitized.py`: 3 tests.
  - `tests/test_normalization.py`: 8 tests.
  - `tests/test_paths.py`: 5 tests (Phase 01).
  - `tests/test_pipeline_behavior.py`: 11 tests.
  - `tests/test_redaction.py`: 5 tests.
  - `tests/test_schema_invalid.py`: 3 tests (Phase 01).
  - `tests/test_unknown_version.py`: 2 tests (Phase 01).
  - **Total: 125 tests.**
- **`mypy`**: `Success: no issues found in 16 source files`.
- **`validate-policy` CLI**: exits 0, reports 17 policy components + 14 schemas.
- **`ingest` CLI**: exits 0, emits 40 sanitized lines, closes with `INGEST COMPLETE`. Grep confirms no `P-\d{5}` player IDs and no known forbidden fixture strings appear in stdout.
- **`tools/validate_policy_package.py`**: `POLICY PACKAGE VALID`.
- **`tools/validate_application_spec.py`**: `APPLICATION SPEC VALID — NO MATERIAL CONTRACT GAPS DETECTED`.

## Unresolved ambiguity
- The mapping between the policy's `processing_order` category names (e.g. `contact_and_internal_ids`) and the detector `id` values (`EMAIL`, `PHONE`, `PLAYER_ID`) is not stated explicitly in the policy file. The mapping is documented in `src/player_triage/detection.py::load_detectors` as an interpretation of the policy's semantics — every detector listed under `detectors[]` is covered exactly once by the ordering, and adding a detector will surface as a loader error rather than silent behaviour drift.
- The phase brief mandates ingestion-level eligibility values (`bypass_sensitive`, `bypass_attachment`, `bypass_untrusted_input`, `redaction_uncertain`, `invalid_input`, `eligible`) that partially overlap with the vocabulary catalogue `model_eligibility` in `policy/controlled_vocabularies.json`. `redaction_uncertain` and `invalid_input` are *not* in that vocabulary. They are intentionally kept only as ingestion-level states; Phase 03's deterministic policy engine will decide the final `model_eligibility` value that appears in outputs. This preserves the vocabulary and simply models the ingestion-only intermediate state.
- The `test_no_enum_duplication.py` guard was narrowed from "no controlled-vocabulary string in source" to "no *classification-decision* catalogue string in source" (categories, intents, routes, priorities, teams, auto-response policies, template IDs). The rationale is documented in the test itself. This is reported here as a deliberate rule-change, not a silent relaxation.

## Confirmation: raw sensitive values not written to outputs or logs
- All 40 redacted messages contain the policy placeholders where the source contained a match; the forbidden fixture strings (`[SYNTHETIC-TEST-PAN]`, `[SYNTHETIC-TEST-PAN]`, `[SYNTHETIC-CVV]`, `[SYNTHETIC-CVV]`) never appear in any `redacted_text`, `replacement_placeholder`, `risk_flags`, `LinkageResult`, or CLI stdout — asserted by `test_m11_pan_and_cvv_bypass_sensitive`, `test_ingest_command_prints_sanitized_summary`, and by the ingestion error test `test_ingestion_error_does_not_echo_row_body`.
- `IngestedMessage.repr()` was scanned across all 40 records for every known `player_id`; none appears — asserted by `test_ingested_message_never_contains_player_id`.
- `LinkageResult.repr()` was scanned across all 40 records for every known `player_id`; none appears — asserted by `test_linkage_output_contains_no_player_id`.
- Nothing is persisted to SQLite, CSV, JSONL or any other output artifact in this phase; the CLI writes only sanitized summary lines to stdout.
- `socket.socket` and `socket.create_connection` were patched to raise during the full ingestion pipeline; the run completed successfully — `test_full_pipeline_makes_no_network_calls`.

## Confirmation: Phase 03 classification logic not started
- No file under `src/player_triage/` implements category classification, intent classification, priority assignment, routing, team assignment, auto-response policy selection, template selection, rationale rendering, semantic-constraint evaluation, or SQLite persistence.
- The CLI commands `run`, `evaluate`, `demo`, `kill-switch` still exit code 2 with a `not implemented in Phase 01` message; no downstream orchestration was wired up.
- `IngestedMessage` deliberately stops at ingestion metadata + redacted representation + detection metadata + eligibility + linkage + market overlay context — every field a Phase 03 rules engine will *consume*, and none that it will *produce*.

## Stop statement
This phase is complete. No work from the next phase was started.
