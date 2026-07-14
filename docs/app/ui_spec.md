# UI Specification — Streamlit Local Control Console

## 1. Dashboard
- Current active configuration version and model mode.
- 40-message run status, category/priority/route distribution, hard-gate status, bypass/manual-review rates, p50/p95 latency.
- Kill-switch control with confirmation and audit event.

## 2. Messages
- Filter by message ID, market, language, category, priority, route, team, risk flag, model eligibility, mismatch status.
- Display redacted preview only; M11 and other sensitive cases never expose raw text.
- Expected vs actual result, rules triggered, reason codes, missing context, model call status, audit event link.

## 3. Human Review
- Queue of human/specialist cases.
- Schema-constrained correction form for category, intent, priority, route, teams, flags and reason codes.
- Before/after preview and required override reason.
- Submit appends a human-override event; original decision remains immutable.

## 4. Policy Studio
Normal form-based editing, not direct editing of active JSON.
- Rule list grouped by Safety, Payments/Security, Responsible Gambling, Complaints, General, Market.
- Show enabled state, order, terminal status, editability, conditions, effects, and policy basis.
- `locked`: view only in normal mode.
- `guarded`: edit with warning and mandatory full regression.
- `editable`: edit normally.
- Pattern tester uses synthetic text or selected redacted fixture and shows matches/non-matches.
- Redaction lab shows placeholder result, detector counts, eligibility and bypass reason.
- Template editor validates owner, ID, approval status and no dynamic placeholders.
- Market-overlay editor changes only allowed routing effects and notes.

## 5. Change Workflow
1. Create draft from active version.
2. Edit form fields; autosave draft only.
3. Run syntax/schema validation.
4. Run semantic validation.
5. Run detector/rule behavioural fixtures.
6. Run impact preview on all 40 cases and synthetic red-team fixtures.
7. Show before/after diffs and hard-gate failures.
8. Block activation when any hard gate fails or a locked rule changed.
9. Require change reason and explicit activation confirmation.
10. Create immutable version, configuration-change event, and activate atomically.
11. Rollback selects a prior valid version, reruns validation/regression, records a rollback event, and activates atomically.

## 6. Evaluation
- Confusion matrix and category/priority/route/team agreement.
- High-risk detection table and all hard gates.
- Mismatch list with expected/actual diff.
- Per-language and per-market slices.
- Export evaluation JSON and mismatch CSV.

## 7. Audit Explorer
- Search by event ID, run ID, message ID, event type, configuration version and date.
- Display decision path, rules, versions, controls, override/change events and diffs.
- No raw message or sensitive values.

## 8. Configuration Versions
- Active/draft/superseded versions, hashes, author, reason, validation status, regression result, activation time.
- Structural diff and human-readable summarized diff.
- Activate/rollback buttons subject to gates.

## 9. Settings
- Rules-only/local-model/model-disabled mode.
- Optional local model path, revision, runtime and timeout.
- No hosted API configuration.
- Output directory and database path.

## UI safety
- All writes go through the configuration manager; the UI never edits active files directly.
- All forms use controlled vocabularies and JSON Schema.
- UI errors are sanitized and never echo raw inputs.
- A change preview is mandatory before activation.
