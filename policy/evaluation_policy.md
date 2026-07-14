# Evaluation Policy

The 40 messages are a demonstration set, not a production accuracy study.

Hard safety gates are non-compensatory. A known critical responsible-gambling, underage, sensitive-payment or active-security false negative fails the demonstration even if aggregate accuracy is high.

Compare exact policy fields:
- category, intent, priority, route, assigned team;
- auto-response policy/template;
- required risk and reason codes;
- market status/overlay and linkage fields.

Do not require an eligible message to call the optional model. Rules-only and model-assisted paths may both be correct. Enforce model non-use only for ground-truth `model_call_policy=forbidden`.

Report raw counts for every metric and every category/language slice. Display every mismatch. Never modify ground truth after viewing output without a separately documented policy-adjudication change.
