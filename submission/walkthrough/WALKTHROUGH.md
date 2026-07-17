# 45-Minute Walkthrough Guide

All commands assume Windows PowerShell from the repository root with the venv
created (see `../README.md`). Prefix: `.\.venv\Scripts\python.exe -m player_triage.cli`.
Everything is local and rules-only; no model is loaded.

## 0–5 min · Context and architecture
- Open `../DECISION_LOG.md` (2 pages) and `../ARCHITECTURE.md`.
- Key points: deterministic authority; model rejected and disabled; no hosted LLM,
  no tools, no attachment processing, no account/payment actions; humans act.

## 5–10 min · Run and outputs
```powershell
.\.venv\Scripts\python.exe -m player_triage.cli validate-policy
.\.venv\Scripts\python.exe -m player_triage.cli run --output-dir output
```
- Confirm: `policy_version: policy-3.3.1`, `mode: rules_only`,
  `counts: input=40 success=40 failure=0 bypass=9`,
  `canonical_decision_sha256: a90de550...`.
- Inspect `output/run_manifest.json` (component + artifact digests, input digest,
  `model_enabled=false`) and open `output/decisions.csv` — note there is **no**
  raw message text, player id, or sensitive value.

## 10–18 min · Dashboard and distributions
```powershell
.\.venv\Scripts\python.exe -m player_triage.cli demo
```
- Browse to the printed `http://127.0.0.1:...` URL. Dashboard: category/priority/
  route/team distributions and bypass counts. Confirm localhost-only binding.

## 18–25 min · Safety cases
In the Messages/Audit pages (or in `output/decisions.jsonl`) inspect:
- **M11** — exposed PAN/CVV → `bypass_sensitive`, critical, specialist, Payments
  Security, `model_called=false`; no card digits anywhere in output.
- **M18** — prompt injection over a withdrawal → `bypass_untrusted_input`, medium,
  human, Payments Operations; injected request ignored.
- **M23 / German RG** — explicit permanent self-exclusion (German) → Responsible
  Gambling, critical, specialist; negated/quoted German phrasings do **not**
  trigger it (see `../evidence/live_change_fixture.md` and the German fixtures).
- **M31** — linked repeat withdrawal + escalation → Complaints & Regulatory, high,
  specialist, with `first_contact_message_id=M09`.

## 25–30 min · M22 mismatch and diagnostics
- `evaluation/mismatch_report.jsonl` → the single core mismatch is **M22 intent**
  (category/priority/route/team correct). Note the **52 set-valued diagnostic
  differences** are secondary-intent/risk-flag sets and change no scored field or
  gate.

## 30–38 min · Safe policy draft and impact preview
- Policy Studio → create a draft that changes only the documented safe field (see
  `../evidence/live_change_fixture.md`): the editable
  `DERIVED_SMALL_BALANCE_DISCREPANCY` rule / a harmless FAQ route.
- Run draft validation + impact preview: schemas + component digests + semantic
  constraints + all locked gates + candidate invariants must pass; the diff shows
  the affected synthetic fixture changes while every safety fixture is unchanged.

## 38–42 min · Activation and before/after
- Activate the draft (literal `ACTIVATE`); re-run `evaluate` and show the intended
  before/after difference on the affected fixture, with 15/15 gates still passing.

## 42–45 min · Rollback, audit evidence, questions
- Roll back (literal `ROLLBACK`) to `policy-3.3.1`; confirm the active version and
  canonical digest are restored. Show the append-only audit events for the draft,
  activation and rollback in the Audit Explorer / `audit_events.jsonl`.

---

## Fallback path (if Streamlit cannot launch)
Everything reviewable without the UI:
```powershell
.\.venv\Scripts\python.exe -m player_triage.cli validate-policy
.\.venv\Scripts\python.exe -m player_triage.cli run --output-dir output
.\.venv\Scripts\python.exe -m player_triage.cli evaluate --output-dir output --performance
.\.venv\Scripts\python.exe -m pytest -q tests/test_phase07_console.py
```
- Safety and gate evidence: `evaluation/safety_gate_results.json`,
  `evaluation/activation_recommendation.json`.
- Configuration-change / activation / rollback semantics are covered by
  `tests/test_phase07_console.py` (governed draft, impact, activation, rollback).
- The recorded run and evaluation artifacts in `outputs/` and `evaluation/` stand
  on their own as evidence.
