from scripts.freeze_llm_baseline_json_adapter import canonical_json, equivalent_json


def test_round_trip_allows_only_json_sequence_representation():
    original = {'validation': [{'lexical': {'signature': {'parameters': ['a'], 'unknowns': []}}}], 'candidates': [{'body': 'x = 1'}]}
    reconstructed = {'validation': [{'lexical': {'signature': {'parameters': ('a',), 'unknowns': ()}}}], 'candidates': [{'body': 'x = 1'}]}
    assert original != reconstructed
    assert equivalent_json(original, reconstructed)
    assert canonical_json(reconstructed) == original


def test_full_validation_content_change_remains_rejected():
    original = {'validation': [{'parameters': ['a'], 'status': 'supported'}], 'candidates': [{'body': 'x = 1'}]}
    different = {'validation': [{'parameters': ('b',), 'status': 'supported'}], 'candidates': [{'body': 'x = 1'}]}
    assert not equivalent_json(original, different)
    assert not equivalent_json(original, {'candidates': original['candidates']})


def test_model_body_change_remains_rejected():
    assert not equivalent_json({'body': 'assert n == 1'}, {'body': 'assert n == 2'})
