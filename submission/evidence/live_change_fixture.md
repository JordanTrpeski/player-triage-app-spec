# Live-Change Demonstration Fixture

The safe field used for the Phase 07/08 draft → activate → rollback demonstration.
It exercises the governed configuration lifecycle without weakening any critical
control. The final submitted state remains `policy-3.3.1` (the demonstration
version is **not** left active).

| Field | Value |
| --- | --- |
| Component | `derived_refinement_rules` (application-layer policy component) |
| Rule / threshold | `DERIVED_SMALL_BALANCE_DISCREPANCY` (small account-specific balance/fee discrepancy routing) |
| Editability class | `editable` (per `policy/ui_editability.json → rule_editability`) |
| Original value | low priority, `human` route, `Payments Operations`, `acknowledgment_only` (no static auto-response) |
| Temporary value (draft) | a benign presentation change to the same editable rule (e.g. an additional reason-code/risk-flag on the same low/human outcome) — never a safety or routing downgrade |
| Expected affected synthetic fixture | a small-balance-discrepancy synthetic case shows the intended before/after diff |
| Expected unaffected safety fixtures | M07 (self-harm/RG), M11 (PAN/CVV bypass), M15 (underage), M18 (injection), M23 (German self-exclusion) and every locked gate remain identical |

The authoritative catalogue of permitted safe changes is
`policy/safety_assertions.json → live_change_demo`
(allowed: repeat-contact escalation threshold `>=1 → >=2`, or a harmless FAQ
route; prohibited: any self-exclusion, self-harm, underage, sensitive-payment or
account-takeover change).

## Validation, activation and rollback commands
Performed through the Policy Studio in `player-triage demo`, or reproduced via the
console-service tests:
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_phase07_console.py
```
Draft validation verifies schemas + component digests + semantic constraints + all
26 locked gates + candidate invariants; activation requires the literal `ACTIVATE`,
current impact evidence and matching draft identity; rollback requires the literal
`ROLLBACK`. All three emit append-only audit events.

## Activation / rollback evidence
- The Phase 07 report documents a completed draft → validate → impact → activate →
  re-evaluate → rollback cycle with 15/15 gates preserved throughout.
- After the demonstration, the active version was restored to `policy-3.3.1` and
  the canonical decision digest `a90de550...` was re-verified.
