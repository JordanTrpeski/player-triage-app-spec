# Phase 04 policy-3.3.0 first-run record

This record freezes the observed Phase 04 policy candidate before remediation.
Neither the archived `policy-3.3.0` manifest/component nor the original
`phase04_semantic_holdout.json` expectations are rewritten.

- Active bundle at first run: `policy-3.3.0`
- Policy-rules SHA-256: `1df7abc807638614825aa58470d2fb62a6e50ef5e629f8417ea334f8f364228c`
- Model-configuration SHA-256: `a5fc86cd6df75f6a58634ed3e9b016dbe986f01b26ef873be8445726d08fd21e`
- Original 16-case holdout SHA-256: `6f5ef1dd24522a78833444728d8880320431d5f7d56b8447894225ec93adc35b`
- Expectations authored before execution: yes

## Observed rules-only result

- Schema/semantic valid: 16/16
- Category agreement: 7/16
- Intent agreement: 5/16
- Secondary-intent agreement: 16/16
- Priority agreement: 10/16
- Route agreement: 11/16
- Assigned-team agreement: 7/16
- Provisional fallbacks: 11/16
- Unsafe auto-responses: 0
- Model calls: 0 (rules-only mode)
- Bypass decisions: 3/16

## Safety failure

Evaluation entry M90 was an explicit German permanent self-exclusion request.
The locked deterministic rule did not match that phrasing, so the rules-only
decision was a model-eligible manual fallback instead of critical Responsible
Gambling specialist routing. In local-model mode this would permit an adapter
call, violating the non-compensatory no-call gate. Policy-3.3.0 is therefore not
an acceptable local-model activation candidate.

The real-model benchmark was interrupted before completion. No complete or
accepted local-model metric is attributed to policy-3.3.0.
