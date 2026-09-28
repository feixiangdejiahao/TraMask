import copy
import json

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.semantics_v2 import SemanticBudget, prepare_requests, validate_response


def prepared(count=1, **budget):
    data = extract_frontend([Source("test_value.py", "def inc(x):\n    return x + 1\ndef test_value():\n    assert inc(2) == 3\n", "python")])
    corpus = to_emitter_corpus(data)
    call = next(c for c in data["calls"] if c["callee"] == "inc")
    candidates = [{"id": "opaque_generated_" + str(i), "base_test_id": data["tests"][0]["id"],
                   "kind": "input_boundary", "edits": [{"span": call["arguments"][0]["span"], "before": "2", "after": "4"}],
                   "oracle": {"mode": "retain_all"}, "relation": {"cell": "boundary"}} for i in range(count)]
    result = prepare_requests(corpus, data, candidates, "The result is input plus one.", SemanticBudget(**budget))
    return corpus, result


def row(cid="C0", expr="arg[0]+1"):
    return {"id": cid, "retain": True, "updates": [{"hole": "H0", "expr": expr}],
            "basis": "The increment contract fixes the result.", "evidence": ["E0"]}


def test_compact_wire_uses_ordinals_and_source_test_only_once():
    _, result = prepared(64)
    request = result["requests"][0]
    wire = json.loads(request["prompt"])
    assert len(wire["candidates"]) == 64
    assert wire["candidates"][0]["id"] == "C0"
    assert wire["candidates"][0]["holes"][0]["id"] == "H0"
    assert len([e for e in wire["evidence"] if e["kind"] == "seed_test"]) == 1
    assert "opaque_generated_" not in request["prompt"]
    assert "start_byte" not in request["prompt"]
    assert "preview" not in request["prompt"]
    assert len(request["prompt"].encode()) < 30_000


def test_valid_ordinal_update_preserves_pure_boundary_and_executes():
    corpus, result = prepared()
    accepted = validate_response(result["requests"][0], {"accepted": [row()]}, corpus=corpus)
    assert not accepted["rejected"]
    candidate = accepted["accepted"][0]
    assert candidate["id"] == "opaque_generated_0"
    assert candidate["edits"][1]["after"] == "5"
    generated = emit(corpus, accepted["accepted"])
    assert not generated["unsupported"]
    namespace = {}
    exec(compile(generated["files"]["test_value.py"], "test_value.py", "exec"), namespace)
    namespace["test_gc_opaque_generated_0"]()


def test_bad_hole_evidence_and_candidate_rows_do_not_erase_valid_neighbors():
    _, result = prepared(5)
    bad_hole = row("C1")
    bad_hole["updates"][0]["hole"] = "H999"
    bad_evidence = row("C2")
    bad_evidence["evidence"] = ["E999"]
    payload = {"accepted": [bad_hole, row("C0"), bad_evidence, row("C404"), row("C3", "inc(4)"), row("C4")]}
    validated = validate_response(result["requests"][0], payload)
    assert [c["id"] for c in validated["accepted"]] == ["opaque_generated_0", "opaque_generated_4"]
    assert len(validated["rejected"]) == 4
    assert "protocol_error" not in validated


def test_first_32_valid_candidates_survive_39_admission_rows():
    _, result = prepared(39)
    payload = {"accepted": [row("C" + str(i)) for i in range(39)]}
    validated = validate_response(result["requests"][0], payload)
    assert len(validated["accepted"]) == 32
    assert len(validated["rejected"]) == 7
    assert all(r["reason"] == "accepted_candidate_budget" for r in validated["rejected"])
    assert "protocol_error" not in validated


def test_malformed_top_level_json_still_rejects_protocol():
    _, result = prepared(2)
    request = result["requests"][0]
    assert "protocol_error" in validate_response(request, '{"accepted": [')
    assert "protocol_error" in validate_response(request, '{"accepted":[],"accepted":[]}')


def test_unused_top_level_metadata_does_not_discard_valid_admission_rows():
    corpus, prepared_result = prepared()
    payload = {'accepted': [row()], 'type': 'object', 'evidence': ['extra explanatory metadata']}
    result = validate_response(prepared_result['requests'][0], payload, corpus=corpus)
    assert len(result['accepted']) == 1
    assert result['ignored_top_level_fields'] == ['evidence', 'type']
    assert result['accepted'][0]['semantic_admission']['evidence'] == ['E0']


def test_alias_tampering_and_injected_input_edits_are_rejected():
    _, result = prepared(2)
    request = copy.deepcopy(result["requests"][0])
    request["candidate_aliases"]["C0"] = "opaque_generated_1"
    assert validate_response(request, {"accepted": [row()]})["protocol_error"] == "frozen_alias_mapping_changed"
    payload = row()
    payload["edits"] = [{"after": "wrong"}]
    validated = validate_response(result["requests"][0], {"accepted": [payload, row("C1")]})
    assert len(validated["accepted"]) == 1
    assert validated["rejected"][0]["reason"] == "invalid_admission_fields"


def test_batch_byte_limit_keeps_only_selected_test_contexts():
    _, result = prepared(100, request_bytes=4_000, max_requests=2)
    assert len(result["requests"]) == 2
    assert all(len(r["prompt"].encode()) <= 4_000 for r in result["requests"])
    assert result["skipped"]
    aliases = [cid for request in result["requests"] for cid in request["candidate_aliases"].values()]
    assert aliases == ["opaque_generated_" + str(i) for i in range(len(aliases))]


def truth_fixture(condition='not result'):
    code = f'''class Probe:
    def __init__(self, value):
        self.value = value
    def __bool__(self):
        observations.append(self.value)
        return self.value
observations = []
def test_value():
    result = Probe(False)
    assert {condition}
'''
    frontend = extract_frontend([Source('test_truth.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    call = next(c for c in frontend['calls'] if c['callee'] == 'Probe')
    candidate = {'id': 'truth_example', 'base_test_id': frontend['tests'][0]['id'],
                 'edits': [{'span': call['arguments'][0]['span'], 'before': 'False', 'after': 'True'}]}
    prepared = prepare_requests(corpus, frontend, [candidate], 'An enabled probe is true.')
    return corpus, prepared['requests'][0]


def test_implicit_truth_expectation_changes_only_polarity_and_observes_once():
    corpus, request = truth_fixture()
    wire = json.loads(request['prompt'])['candidates'][0]
    assert wire['holes'][0]['fixed_type'] == 'bool'
    assert wire['holes'][0]['observed_truth_of'] == 'result'
    assert wire['holes'][0]['old_expected'] is False
    accepted = validate_response(request, {'accepted': [row(expr='True')]}, corpus=corpus)
    assert len(accepted['accepted']) == 1
    generated = emit(corpus, accepted['accepted'])
    namespace = {}
    exec(generated['files']['test_truth.py'], namespace)
    namespace['test_gc_truth_example']()
    assert namespace['observations'] == [True]
    assert accepted['accepted'][0]['edits'][-1]['after'] == '(result)'


def test_truth_expectation_retaining_old_value_does_not_rewrite_observation():
    corpus, request = truth_fixture()
    accepted = validate_response(request, {'accepted': [row(expr='pre[0]')]}, corpus=corpus)
    assert len(accepted['accepted'][0]['edits']) == 1
    assert accepted['accepted'][0]['oracle']['mode'] == 'semantic_retain_all'


def test_truth_expected_hole_cannot_become_constant_or_integer():
    corpus, request = truth_fixture()
    rejected = validate_response(request, {'accepted': [row(expr='1')]}, corpus=corpus)
    assert not rejected['accepted']
    assert rejected['rejected'][0]['reason'] == 'source_template_leaf_type_changed'
    positive_corpus, positive_request = truth_fixture('result')
    accepted = validate_response(positive_request, {'accepted': [row(expr='False')]}, corpus=positive_corpus)
    assert accepted['accepted'][0]['edits'][-1]['after'] == 'not (result)'
