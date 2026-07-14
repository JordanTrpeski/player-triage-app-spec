from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
POL = ROOT / "policy"
SCH = ROOT / "schemas"
INP = ROOT / "input"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def fail(message: str):
    print(f"FAIL: {message}")
    raise SystemExit(1)


def compile_regex(pattern: str, location: str):
    try:
        re.compile(pattern)
    except re.error as exc:
        fail(f"invalid regex at {location}: {pattern!r}: {exc}")


def walk_match_regex(node, location: str):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"regex_any", "regex_all"}:
                for index, pattern in enumerate(value):
                    compile_regex(pattern, f"{location}.{key}[{index}]")
            else:
                walk_match_regex(value, f"{location}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            walk_match_regex(item, f"{location}[{index}]")


def validate_rule_effects(rule, vocab):
    rid = rule["id"]
    effects = rule.get("effects", {})
    scalar_catalogues = {
        "category": "categories",
        "intent": "intents",
        "priority": "priorities",
        "route": "routes",
        "assigned_team": "teams",
        "model_eligibility": "model_eligibility",
        "model_bypass_reason": "model_bypass_reasons",
        "auto_response_policy": "auto_response_policies",
        "auto_response_template_id": "auto_response_template_ids",
    }
    array_catalogues = {
        "risk_flags": "risk_flags",
        "reason_codes": "reason_codes",
        "secondary_teams": "teams",
        "secondary_intents": "intents",
    }
    for field, value in effects.get("set", {}).items():
        catalogue = scalar_catalogues.get(field)
        if catalogue and value is not None and value not in vocab[catalogue]:
            fail(f"{rid}: unknown {field} value {value!r}")
    for field, values in effects.get("add", {}).items():
        catalogue = array_catalogues.get(field)
        if catalogue:
            unknown = sorted(set(values) - set(vocab[catalogue]))
            if unknown:
                fail(f"{rid}: unknown {field} values {unknown}")


def main():
    vocab = load_json(POL / "controlled_vocabularies.json")
    schemas = {
        "ground truth": load_json(SCH / "ground_truth_schema.json"),
        "output": load_json(SCH / "output_schema.json"),
        "audit": load_json(SCH / "audit_event_schema.json"),
        "model": load_json(SCH / "model_candidate_schema.json"),
    }
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        print(f"OK schema: {name}")

    ground_truth = load_jsonl(POL / "ground_truth_40.jsonl")
    validator = Draft202012Validator(schemas["ground truth"])
    for line_number, record in enumerate(ground_truth, 1):
        errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
        if errors:
            fail(f"ground truth line {line_number}: " + "; ".join(error.message for error in errors))

    expected_ids = [f"M{index:02d}" for index in range(1, 41)]
    ids = [record["message_id"] for record in ground_truth]
    if ids != expected_ids:
        fail(f"ground truth IDs/order mismatch: {ids}")
    if len(set(ids)) != 40:
        fail("duplicate ground-truth IDs")

    with (INP / "dataset_player_messages.csv").open(newline="", encoding="utf-8") as file:
        input_rows = list(csv.DictReader(file))
    required_input_columns = [
        "msg_id", "received_utc", "channel", "market", "player_id",
        "vip_tier", "language", "subject", "body",
    ]
    if list(input_rows[0].keys()) != required_input_columns:
        fail(f"input CSV columns mismatch: {list(input_rows[0].keys())}")
    if [row["msg_id"] for row in input_rows] != expected_ids:
        fail("input CSV IDs/order mismatch")
    if not (INP / "dataset_player_messages.xlsx").exists():
        fail("input workbook missing")

    templates = load_json(POL / "auto_response_templates.json")
    template_ids = [template["id"] for template in templates["templates"]]
    if len(template_ids) != len(set(template_ids)):
        fail("duplicate auto-response template IDs")
    if set(template_ids) != set(vocab["auto_response_template_ids"]):
        fail("template IDs do not match controlled vocabulary")
    for template in templates["templates"]:
        if template["owner"] not in vocab["teams"]:
            fail(f"template {template['id']}: unknown owner {template['owner']}")

    for record in ground_truth:
        result = record["expected_result"]
        message_id = record["message_id"]
        if result["route"] == "auto_respond":
            valid = (
                result["priority"] == "low"
                and result["auto_response_policy"] == "allowed_template"
                and result["auto_response_template_id"] in template_ids
                and not result["human_review_required"]
            )
            if not valid:
                fail(f"{message_id}: invalid auto-response combination")
        else:
            if result["auto_response_template_id"] is not None or not result["human_review_required"]:
                fail(f"{message_id}: human/specialist cross-field inconsistency")
        if record["expected_processing"]["model_call_policy"] == "forbidden" and not result["model_eligibility"].startswith("bypass_"):
            fail(f"{message_id}: model forbidden but eligibility not bypass")
        if result["attachment_received"] and result["model_eligibility"] not in {"eligible_text_only", "bypass_attachment"}:
            fail(f"{message_id}: attachment-received eligibility inconsistent")
        if result["model_bypass_reason"] is not None and result["model_bypass_reason"] not in vocab["model_bypass_reasons"]:
            fail(f"{message_id}: uncontrolled model bypass reason")

    policy_rules = load_json(POL / "policy_rules.json")
    rule_ids = []
    for index, rule in enumerate(policy_rules["rules"]):
        rule_ids.append(rule["id"])
        walk_match_regex(rule.get("match", {}), f"policy_rules[{index}].match")
        validate_rule_effects(rule, vocab)
    if len(rule_ids) != len(set(rule_ids)):
        fail("duplicate policy rule IDs")

    baseline_rules = load_json(POL / "baseline_intent_rules.json")
    baseline_ids = []
    for index, rule in enumerate(baseline_rules["rules"]):
        baseline_ids.append(rule["id"])
        if rule["category"] not in vocab["categories"]:
            fail(f"baseline rule {rule['id']}: unknown category")
        if rule["intent"] not in vocab["intents"]:
            fail(f"baseline rule {rule['id']}: unknown intent")
        for pattern_index, pattern in enumerate(rule["patterns"]):
            compile_regex(pattern, f"baseline_rules[{index}].patterns[{pattern_index}]")
    if len(baseline_ids) != len(set(baseline_ids)):
        fail("duplicate baseline rule IDs")

    redaction = load_json(POL / "redaction_policy.json")
    for detector_index, detector in enumerate(redaction["detectors"]):
        for pattern_index, pattern in enumerate(detector.get("patterns", [])):
            compile_regex(pattern, f"redaction.detectors[{detector_index}].patterns[{pattern_index}]")
        if "candidate_pattern" in detector:
            compile_regex(detector["candidate_pattern"], f"redaction.detectors[{detector_index}].candidate_pattern")
    for pattern_index, pattern in enumerate(redaction["prompt_injection_patterns"]):
        compile_regex(pattern, f"redaction.prompt_injection_patterns[{pattern_index}]")

    assertions = load_json(POL / "safety_assertions.json")
    assertion_ids = [item["id"] for item in assertions["hard_gates"]]
    if len(assertion_ids) != len(set(assertion_ids)):
        fail("duplicate safety assertion IDs")
    for item in assertions["hard_gates"]:
        for message_id in ([item["message_id"]] if "message_id" in item else item.get("message_ids", [])):
            if message_id not in expected_ids:
                fail(f"{item['id']}: unknown message ID {message_id}")

    forbidden = ["4539 1488 0343 6467", "4539148803436467", "CVV 441", "cvv 441"]
    for path in list(POL.glob("*")) + list(SCH.glob("*")) + list((ROOT / "coding_runbook").rglob("*")) + list((ROOT / "docs").glob("*")):
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".csv", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        for value in forbidden:
            if value in text:
                fail(f"sensitive fixture leaked into {path.relative_to(ROOT)}")

    print("OK ground truth: 40 records")
    print("OK input CSV: 40 records and expected columns")
    print("OK controlled vocabularies and templates")
    print("OK policy/baseline rule references and regexes")
    print("OK redaction regexes")
    print("OK safety assertion references")
    print("OK cross-field constraints")
    print("OK no known sensitive fixture values in generated artifacts")
    print("POLICY PACKAGE VALID")


if __name__ == "__main__":
    main()
