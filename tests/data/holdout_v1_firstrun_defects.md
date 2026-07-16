# Holdout-v1 first-run defect record (historical artifact)

`tests/data/synthetic_holdout.json` (holdout-v1) is preserved unchanged as both a
historical evaluation artifact and a discovered-defect regression set. Its
expected results were written before the Phase 03C run and were **not** modified
in Phase 03D. This file records the original Phase 03C first-run failures so the
corrections are auditable.

## Phase 03C first-run failures (as discovered)

| id | challenge | first-run result (03C) | expected | defect |
| --- | --- | --- | --- | --- |
| M50 | actual OTP/password value | `model_eligibility=eligible`, medium/human (fell to a model-eligible generic fallback) | `bypass_sensitive`, critical/specialist | **false negative**: a detected secret was dropped to a model-eligible path |
| M59 | prompt injection around a bonus | `model_eligibility=eligible` (fell to fallback) | `bypass_untrusted_input`, business classified | **false negative**: a detected injection was dropped to a model-eligible path |
| M60 | negated self-exclusion | Responsible Gambling / explicit_permanent_self_exclusion / critical | General / non-escalated | **false positive**: negated self-exclusion triggered the critical rule |

## Phase 03D correction (root causes)

* M50 and M59 were actually **detected** by the ingestion detectors; the defect
  was the **engine fallback discarding safety/injection routing** when no business
  classification survived. The engine now preserves `bypass_sensitive` /
  `bypass_untrusted_input` (and the safety-terminal routing) in the fallback path,
  so a detected secret or injection is never sent to a model-eligible path.
* AUTH_SECRET value-bearing detection and prompt-injection phrase families were
  additionally broadened in policy (`redaction_policy.json`).
* M60 was corrected by adding negation/informational/quoted guards to the explicit
  self-exclusion rule (`policy_rules.json`); harm/loss-of-control still escalates.

After Phase 03D, re-running holdout-v1 yields **0 false positives and 0 false
negatives** on the recorded findings; the defects are corrected while the expected
results remain unchanged.
