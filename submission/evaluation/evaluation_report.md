# Phase 06 Evaluation Report

This is a synthetic demonstration evaluation, not production accuracy or compliance validation.

## Dataset results (kept separate)

| Dataset | Messages | Category | Intent | Schema valid | Mismatches |
|---|---:|---:|---:|---:|---:|
| supplied-40 | 40 | 40/40 | 39/40 | 40/40 | 1 |
| holdout-v1 | 25 | 22/25 | 21/25 | 25/25 | 10 |
| holdout-v2 | 18 | 18/18 | 18/18 | 18/18 | 0 |

## Supplied-set approved mismatches

- M22 `intent`: expected `withdrawal_delay`, actual `withdrawal_status_first_contact` (approved_baseline_mismatch).

## Additional set-valued diagnostic differences

- 52 differences are reported in the machine-readable mismatch table for secondary teams, risk flags, and reason codes.
- These are measured transparently but do not redefine the accepted M22-only deterministic baseline.

## Safety and activation

- Locked gates: 26/26 passed.
- Activation recommendation: `eligible_for_controlled_review`.
- Model calls: 0.

## Performance and capacity

- Measured rules-only throughput: 21.75 messages/second.
- Illustrative 900-message compute time: 41.38 seconds/day.
- Recommended batch/concurrency: 100 / 1.

## Human review

- Supplied set: auto=10, human=16, specialist=14.
- The 900-message/day extrapolation is illustrative and not statistically representative.

No Streamlit, Policy Studio, external integration, hosted model, or autonomous action is included.
