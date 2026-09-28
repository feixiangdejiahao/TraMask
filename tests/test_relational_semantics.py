"""Independent toy contracts for the bounded semantic-edit boundary."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.semantics import SemanticBudget, prepare_requests, validate_response


def setup_case(code=None, language="python", path="test_value.py"):
    code = code or "def inc(x):\n    return x + 1\n\ndef test_seed():\n    assert inc(2) == 3\n"
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    call = next(c for c in frontend["calls"] if c["callee"] == "inc")
    argument = call["arguments"][0]
    candidate = {"id": "candidate_1", "base_test_id": frontend["tests"][0]["id"],
                 "source_test_ids": [], "kind": "literal_boundary", "language": language,
                 "edits": [{"span": argument["span"], "before": argument["text"], "after": "4"}],
                 "relation": {"kind": "numeric_boundary"},
                 "oracle": {"mode": "retain_all", "assertion_ids": [frontend["observations"][0]["id"]]}}
    prepared = prepare_requests(corpus, frontend, [candidate], "inc returns its input plus one.")
    return corpus, frontend, candidate, prepared["requests"][0]


def decision(request, expression=None):
    offered = request["offered"][0]
    return {"accepted": [{"id": offered["id"], "retain": True,
                           "updates": [] if expression is None else [{"hole": offered["holes"][0]["id"], "expr": expression}],
                           "basis": "The issue specifies the increment contract.", "evidence": ["issue"]}]}


def test_request_offers_only_source_generated_candidate_and_known_slots():
    corpus, frontend, candidate, request = setup_case()
    prompt = json.loads(request["prompt"])
    assert prompt["candidates"][0]["id"] == candidate["id"]
    assert prompt["candidates"][0]["pre"] == [3]
    assert prompt["candidates"][0]["arg"] == [4]
    assert "inc(4)" in prompt["candidates"][0]["preview"]
    assert "actual" not in prompt["candidates"][0]
    assert request["candidate_records"][0] == candidate
    assert request["candidate_records"][0] is not candidate


def test_pure_completion_updates_expected_only_and_generated_test_executes():
    corpus, frontend, candidate, request = setup_case()
    result = validate_response(request, decision(request, "arg[0] + 1"), corpus=corpus)
    assert not result["rejected"]
    accepted = result["accepted"][0]
    assert accepted["edits"][0] == candidate["edits"][0]
    assert accepted["edits"][1]["before"] == "3"
    assert accepted["edits"][1]["after"] == "5"
    assert accepted["oracle"]["applicability"] == "model_admitted_not_independently_proved"
    generated = emit(corpus, [accepted])
    assert not generated["unsupported"]
    namespace = {}
    exec(compile(generated["files"]["test_value.py"], "test_value.py", "exec"), namespace)
    namespace["test_gc_candidate_1"]()
    assert corpus["sources"]["test_value.py"]["code"].endswith("assert inc(2) == 3\n")


def test_explicit_retention_without_update_is_recorded_as_model_judgment():
    corpus, _, candidate, request = setup_case()
    result = validate_response(request, decision(request), corpus=corpus)
    accepted = result["accepted"][0]
    assert accepted["edits"] == candidate["edits"]
    assert accepted["oracle"]["mode"] == "semantic_retain_all"
    assert accepted["semantic_admission"]["retain_other_assertions"] is True


def test_source_local_expected_constant_supplies_pre_without_new_edit_site():
    corpus, _, _, request = setup_case('def inc(x):\n    return x + 1\ndef test_seed():\n    want = 3\n    assert inc(2) == want\n')
    offered = request['offered'][0]
    assert offered['pre'] == [3]
    assert offered['holes'][0]['before'] == 'want'
    assert offered['holes'][0]['kind'] == 'source_local_constant'
    result = validate_response(request, decision(request, 'pre[0] + 2'), corpus=corpus)
    assert not result['rejected']
    accepted = result['accepted'][0]
    assert accepted['edits'][-1]['before'] == 'want'
    output = emit(corpus, [accepted])
    namespace = {}
    exec(output['files']['test_value.py'], namespace)
    namespace[output['obligations'][0]['test_name']]()
    assert 'want = 3' in output['files']['test_value.py']


@pytest.mark.parametrize("expression", [
    "inc(arg[0])", "__import__('os').system('false')", "actual", "pre.__class__",
    "[x for x in pre]", "True if True else inc(2)",
])
def test_arbitrary_calls_actual_values_and_hidden_unsafe_branches_are_rejected(expression):
    corpus, _, _, request = setup_case()
    result = validate_response(request, decision(request, expression), corpus=corpus)
    assert not result["accepted"]
    assert result["rejected"][0]["reason"] == "impure_expression"


def test_model_cannot_choose_spans_or_change_input_code():
    _, _, _, request = setup_case()
    payload = decision(request, "5")
    payload["accepted"][0]["updates"][0]["span"] = request["candidate_records"][0]["edits"][0]["span"]
    result = validate_response(request, payload)
    assert not result["accepted"]
    assert result["protocol_error"] == "updates_require_only_hole_and_expr"


def test_unknown_id_and_duplicate_json_keys_reject_entire_response():
    _, _, _, request = setup_case()
    payload = decision(request)
    payload["accepted"][0]["id"] = "invented_test"
    assert validate_response(request, payload)["protocol_error"] == "unknown_or_duplicate_candidate"
    result = validate_response(request, '{"accepted":[],"accepted":[]}')
    assert result["protocol_error"] == "duplicate_json_key"


def test_omitted_candidate_is_unknown_not_validated_or_rejected():
    _, _, _, request = setup_case()
    result = validate_response(request, {"accepted": []})
    assert not result["accepted"]
    assert not result["rejected"]
    assert result["unknown"] == [{"candidate_id": "candidate_1", "reason": "not_admitted_by_model"}]


def test_retention_and_nonempty_contract_evidence_are_required():
    _, _, _, request = setup_case()
    for field, value in [("retain", False), ("basis", ""), ("evidence", []), ("evidence", ["invented_source"])]:
        payload = decision(request)
        payload["accepted"][0][field] = value
        assert "protocol_error" in validate_response(request, payload)


def test_frozen_candidate_holes_and_source_snapshot_are_checked():
    corpus, _, _, request = setup_case()
    tampered = copy.deepcopy(request)
    tampered["candidate_records"][0]["edits"][0]["after"] = "99"
    assert validate_response(tampered, {"accepted": []})["protocol_error"] == "frozen_candidate_records_changed"
    tampered = copy.deepcopy(request)
    tampered["offered"][0]["holes"][0]["span"]["start_byte"] = 0
    assert validate_response(tampered, {"accepted": []})["protocol_error"] == "frozen_expected_holes_changed"
    corpus["sources"]["test_value.py"]["code"] += "# modified\n"
    assert validate_response(request, {"accepted": []}, corpus=corpus)["protocol_error"] == "source_snapshot_changed"


def test_existing_constructor_keeps_fixed_source_skeleton():
    corpus, _, _, request = setup_case("""
def inc(x):
    return Pair(x, x + 1)

def test_seed():
    assert inc(2) == Pair(2, 3)
""")
    holes = request["offered"][0]["holes"]
    assert [hole["kind"] for hole in holes] == ["source_template_leaf", "source_template_leaf"]
    payload = decision(request)
    payload["accepted"][0]["updates"] = [{"hole": holes[0]["id"], "expr": "arg[0]"},
                                            {"hole": holes[1]["id"], "expr": "arg[0] + 1"}]
    result = validate_response(request, payload, corpus=corpus)
    generated = emit(corpus, result["accepted"])
    assert "assert inc(4) == Pair(4, 5)" in generated["files"]["test_value.py"]
    assert all("Pair" not in edit["after"] for edit in result["accepted"][0]["edits"])
    bad = decision(request, "'wrong type'")
    assert validate_response(request, bad)["rejected"][0]["reason"] == "source_template_leaf_type_changed"


def test_unknown_expected_identifier_can_only_become_closed_literal():
    corpus, _, _, request = setup_case("def test_seed():\n    assert inc(2) == CONSTANT\n")
    hole = request["offered"][0]["holes"][0]
    assert hole["kind"] == "unknown_source_expected"
    assert hole["pre_index"] is None
    result = validate_response(request, decision(request, "5"), corpus=corpus)
    assert result["accepted"][0]["edits"][1]["before"] == "CONSTANT"
    assert result["accepted"][0]["edits"][1]["after"] == "5"


def test_typescript_uses_target_literal_emission():
    corpus, _, _, request = setup_case('function inc(x: number) { return x + 1; }\ntest("sample", () => { expect(inc(2)).toBe(3); });\n',
                                       "typescript", "value.test.ts")
    result = validate_response(request, decision(request, "arg[0] + 1"), corpus=corpus)
    assert result["accepted"][0]["edits"][1]["after"] == "5"
    assert not emit(corpus, result["accepted"])["unsupported"]


def test_exception_classes_are_retention_only_not_literal_holes():
    corpus, _, _, request = setup_case('import pytest\ndef test_seed():\n    with pytest.raises(ValueError):\n        inc(2)\n')
    assert request["offered"][0]["holes"] == []
    assert len(validate_response(request, decision(request), corpus=corpus)["accepted"]) == 1


def test_fixed_candidate_request_and_admission_budgets():
    corpus, frontend, candidate, _ = setup_case()
    candidates = [dict(candidate, id="candidate_" + str(i)) for i in range(140)]
    prepared = prepare_requests(corpus, frontend, candidates, "The increment contract holds.")
    assert len(prepared["requests"]) == 2
    assert all(len(request["offered"]) <= 64 for request in prepared["requests"])
    assert len(prepared["skipped"]) >= 12
    request = prepared["requests"][0]
    payload = {"accepted": [{"id": offered["id"], "retain": True, "updates": [],
                              "basis": "Source contract", "evidence": ["issue"]}
                             for offered in request["offered"][:33]]}
    assert validate_response(request, payload)["protocol_error"] == "response_budget_exceeded"
    for kwargs in ({"max_requests": 3}, {"candidates_per_request": 65}, {"max_accepted": 33}):
        with pytest.raises(ValueError):
            SemanticBudget(**kwargs)


def test_invalid_program_edits_and_unchecked_output_are_not_offered():
    corpus, frontend, candidate, _ = setup_case()
    wrong = copy.deepcopy(candidate)
    wrong["edits"][0]["before"] = "mismatch"
    prepared = prepare_requests(corpus, frontend, [wrong], "contract")
    assert not prepared["requests"]
    assert prepared["skipped"][0]["reason"] == "candidate_input_edit_not_source_owned"
    raw = extract_frontend([Source("trajectory/raw.py", "value = inc(2)\nprint(value)\n", "python", "trajectory")])
    corpus = to_emitter_corpus(raw)
    candidate = dict(candidate, base_test_id=raw["tests"][0]["id"], edits=[])
    prepared = prepare_requests(corpus, raw, [candidate], "contract")
    assert not prepared["requests"]
    assert prepared["skipped"][0]["reason"] == "no_existing_checked_observation"
