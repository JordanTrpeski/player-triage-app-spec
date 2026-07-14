# Rule DSL 3.0

Rules are ordered and run in `pre_model` or `post_semantic` phases.

A rule contains:
- `id`, `order`, `enabled`, `phase`, `terminal`;
- `editability`: `locked`, `guarded`, or `editable`;
- `ui_group` for Policy Studio;
- recursive `match` conditions using `any`, `all`, flag equality, `regex_any`, and `regex_none`;
- `effects.set` for authoritative scalar fields;
- `effects.add` for risk flags, reason codes, secondary intents and secondary teams;
- `policy_basis_ids` and control classification.

`terminal=true` stops later classification rules after its effects are applied. A model candidate never overrides a terminal pre-model result. Pattern changes are compiled and behavior-tested before configuration activation.
