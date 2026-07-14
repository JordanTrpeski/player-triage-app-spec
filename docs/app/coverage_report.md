# Application Coverage Report — v3.0

All mandatory application requirements have an implementation contract and verification method.

| ID | Area | Requirement | Implemented by | Verified by |
|---|---|---|---|---|
| APP-001 | Input | Load and validate canonical CSV/XLSX | input adapter | test_input_equivalence |
| APP-002 | Classification | One of eight categories and four priorities | output schema + policy engine | ground truth integration |
| APP-003 | Routing | Route and named team | output schema + policy engine | ground truth integration |
| APP-004 | Privacy | Local sensitive detection/redaction before model | redaction service | behaviour fixtures |
| APP-005 | Safety | Deterministic high-risk precedence | pre-model rules | safety assertions |
| APP-006 | Model | Optional local model with no authority | provider interface + model schema | adapter contract tests |
| APP-007 | Attachments | No raw attachment in model path | attachment gate | synthetic A01 |
| APP-008 | Audit | CSV and append-only JSONL | export + audit writer | schema/export tests |
| APP-009 | Human control | Append-only overrides | review service + UI | override event test |
| APP-010 | Changes | Draft/validate/impact/activate/rollback | configuration manager + UI | change lifecycle tests |
| APP-011 | Evaluation | 40-case metrics and hard gates | evaluation service | evaluation schema |
| APP-012 | Reliability | Fail closed and kill switch | pipeline controller | failure-injection tests |
| APP-013 | UI | Dashboard/messages/review/policy/evaluation/audit/version/settings | Streamlit UI | UI smoke tests |
| APP-014 | Market | Consistent market overlays | market overlay service | market tests |
| APP-015 | Linkage | Repeat-contact linkage without output player ID | linkage service | M09/M31 test |
| APP-016 | Templates | Approved static template selection only | template service | route/template semantic tests |
| APP-017 | No actions | No account/payment/self-exclusion execution | architecture boundary | negative capability tests |

## Contract validation
- All editable policy files have dedicated JSON Schemas.
- All 40 ground-truth records validate.
- Detector, deterministic-rule and baseline-classifier behavior fixtures pass.
- Complete decisions and decision audit events validate for all 40 records.
- Unsafe route/model/market combinations are rejected by schema and semantic constraints.
- UI changes require draft, validation, impact preview, regression, activation audit and rollback.

No material application-contract gap remains. Implementation defects may still be discovered during coding and must be resolved against this specification.
