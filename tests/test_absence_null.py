import ast
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import absence_null as relation
from relation_search import compact_contract_guarded


PARAMETRIZED = '''import json
import pytest
from example import validate, Invalid

@pytest.mark.parametrize("payload", [
    {"quota": "bad", "location": "α"},
    {"quota": -2, "location": "β"},
])
def test_validation(tmp_path, payload):
    file = tmp_path / "config.json"
    file.write_text(json.dumps(payload))
    with pytest.raises(Invalid):
        validate(file)
'''

KEYWORD = '''import pytest
from example import save, validate

BASE = {"kind": "record"}

def test_bad_count(tmp_path):
    file = tmp_path / "bundle"
    save(file, dict(BASE, quantity=5), [1])
    errors = validate(file)
    assert any("quantity" in error for error in errors)
'''


def fixture(code, *, path='test_inputs.py', origin='repository'):
    source = Source(path, code, 'python', origin)
    frontend = extract_frontend([source])
    corpus = to_emitter_corpus(frontend)
    for rank, test in enumerate(corpus['tests'].values()):
        test['retrieval_rank'] = rank
    return corpus, frontend


def generate(code, issue='quota location quantity field', **kwargs):
    corpus, frontend = fixture(code, **kwargs)
    before = copy.deepcopy((corpus, frontend))
    result = relation.generate(corpus, frontend, issue)
    assert (corpus, frontend) == before
    json.dumps(result)
    return result, corpus, frontend


def test_literal_parameter_rows_preserve_all_decorators_rows_and_error_checks():
    result, corpus, _ = generate(PARAMETRIZED, issue='quota is optional; if present it must be an integer.')
    assert result['total_candidates'] == 2
    first = result['candidates'][0]
    assert first['edits'][0]['before'] == '"bad"'
    assert first['edits'][0]['after'] == 'None'
    assert first['source_evidence']['container_kind'] == 'dictionary_literal'
    assert first['source_evidence']['null_illegality_established'] is False
    assert first['source_evidence']['original_test']['text'].startswith('@pytest.mark.parametrize')
    assert first['source_test_ids'] == [first['base_test_id']]
    emitted = emit(corpus, [first])
    assert not emitted['unsupported']
    code = emitted['files']['test_inputs.py']
    parsed = ast.parse(code)
    # The emitter can choose another registration prefix. Locate the only
    # function whose first parameter row contains the requested null edit.
    generated = [n for n in parsed.body if isinstance(n, ast.FunctionDef)
                 and n.decorator_list and ast.literal_eval(n.decorator_list[0].args[1])[0]['quota'] is None]
    assert len(generated) == 1
    original = ast.parse(PARAMETRIZED).body[-1]
    assert ast.dump(generated[0].body[0]) == ast.dump(original.body[0])
    assert ast.dump(generated[0].body[-1]) == ast.dump(original.body[-1])
    assert ast.literal_eval(generated[0].decorator_list[0].args[1])[1]['quota'] == -2
    assert '"location": "α"' in code


def test_builtin_dict_keyword_and_non_raising_error_observation_are_preserved():
    result, corpus, frontend = generate(KEYWORD)
    assert result['total_candidates'] == 1
    candidate = result['candidates'][0]
    evidence = candidate['source_evidence']
    assert evidence['field'] == 'quantity'
    assert evidence['container_kind'] == 'builtin_dict_keyword'
    assert evidence['input_argument_bindings'][0]['binding'] == ['example', 'save']
    assert candidate['edits'][0]['before'] == '5'
    emitted = emit(corpus, [candidate])
    assert not emitted['unsupported']
    assert 'dict(BASE, quantity=None)' in emitted['files']['test_inputs.py']
    assert emitted['files']['test_inputs.py'].count('assert any("quantity" in error for error in errors)') >= 2
    review = compact_contract_guarded.prepare(corpus, frontend, candidate,
        'quantity is optional. If present it must be an integer. validate returns field-specific errors.',
        max_prompt_bytes=100000)
    assert review['request'] is not None
    payload = json.loads(review['request']['prompt'])
    assert 'quantity=5' in payload['original_test']
    assert 'quantity=None' in payload['modified_test']
    assert payload['modified_test'].endswith('assert any("quantity" in error for error in errors)')


def test_static_subscript_value_reaches_same_unique_local_dictionary():
    code = '''from example import inspect
def test_mapping():
    payload = {}
    payload["quota"] = 4
    errors = inspect(payload)
    assert errors
'''
    result, _, _ = generate(code)
    assert result['total_candidates'] == 1
    assert result['catalog'][0]['container_kind'] == 'subscript_assignment'


@pytest.mark.parametrize('code', [
    'from example import inspect\ndef test_x():\n    assert inspect() == {"quota": 1}\n',
    'from example import inspect\ndef test_x():\n    expected = {"quota": 1}\n    alias = expected\n    assert inspect() == alias\n',
    'from example import inspect, normalize\ndef test_x():\n    expected = {"quota": 1}\n    alias = normalize(expected)\n    assert inspect() == alias\n',
    'from example import inspect\ndef check(value):\n    assert inspect() == value\ndef test_x():\n    check({"quota": 1})\n    assert True\n',
    'from example import inspect\ndef test_x():\n    payload = {"quota": 1}\n    alias = payload\n    assert inspect() == alias\n',
    'from example import inspect\ndef test_x():\n    payload = {"quota": 1}\n    payload = {"quota": 2}\n    errors = inspect(payload)\n    assert errors\n',
    'from example import inspect\ndef test_x():\n    payload = {"quota": 1}\n    payload["other"] = 2\n    errors = inspect(payload)\n    assert errors\n',
    'from example import inspect\ndef test_x():\n    payload = {"quota": 1}\n    payload |= {}\n    errors = inspect(payload)\n    assert errors\n',
    'from example import inspect\ndef test_x():\n    global payload\n    payload = {"quota": 1}\n    errors = inspect(payload)\n    assert errors\n',
    'from example import inspect\ndef test_x():\n    payload = {"quota": 1}\n    callback = lambda: inspect(payload)\n    assert callback()\n',
])
def test_oracle_construction_aliases_rebinding_mutation_and_capture_abstain(code):
    result, _, _ = generate(code)
    assert result['candidates'] == []


@pytest.mark.parametrize('prefix,parameter', [
    ('dict = custom\n', ''), ('from example import dict\n', ''),
    ('def dict(*args, **kwargs):\n    return {}\n', ''),
    ('from example import *\n', ''), ('', ', dict'),
])
def test_shadowed_dict_is_not_a_constructor(prefix, parameter):
    code = KEYWORD.replace('def test_bad_count(tmp_path):', f'def test_bad_count(tmp_path{parameter}):')
    code = prefix + code
    result, _, _ = generate(code)
    assert result['candidates'] == []


def test_shadowed_pytest_and_indirect_parametrization_abstain():
    for code in [PARAMETRIZED.replace('from example import validate, Invalid',
                                      'from example import validate, Invalid\npytest = replacement'),
                 PARAMETRIZED.replace('])\ndef test_validation', '], indirect=True)\ndef test_validation')]:
        assert generate(code)[0]['candidates'] == []


def test_parametrized_values_used_to_construct_expected_results_abstain():
    code = '''import pytest
from example import actual, normalize
@pytest.mark.parametrize("payload", [{"quota": 1}])
def test_expected(payload):
    expected = normalize(payload)
    assert actual() == expected
'''
    result, _, _ = generate(code)
    assert not result['candidates']
    assert any(s['reason'] == 'source_expected_value_dependency' for s in result['skipped'])


def test_truncated_original_span_cannot_drop_any_final_assertion():
    corpus, frontend = fixture(KEYWORD)
    selected = next(iter(corpus['tests'].values()))
    selected['span']['end_byte'] -= 10
    result = relation.generate(corpus, frontend, 'quantity')
    assert not result['candidates']
    assert result['skipped'][0]['reason'] == 'incomplete_original_test_span'


def test_rename_modules_apis_tests_and_fields_without_case_or_path_rules():
    code = KEYWORD.replace('example', 'other_library').replace('save', 'persist').replace('validate', 'examine').replace(
        'test_bad_count', 'test_another').replace('quantity', 'ceiling')
    result, _, _ = generate(code, issue='ceiling must be an integer when present.', path='elsewhere/test_renamed.py')
    assert result['total_candidates'] == 1
    assert result['catalog'][0]['field'] == 'ceiling'


def test_full_identifier_matching_non_none_scalars_and_fixed_limit():
    code = 'from example import consume\ndef test_x():\n'
    code += '\n'.join(f'    consume({{"quota": {i}}})' for i in range(20))
    code += '\n    consume({"quota": None, "quotas": 1, "quota_name": 2})\n    assert True\n'
    result, corpus, frontend = generate(code, issue='quota')
    assert result['total_candidates'] == 20
    assert len(result['candidates']) == 16
    assert [c['edits'][0]['before'] for c in result['candidates']] == [str(i) for i in range(16)]
    for bad in [17, -1, True, 1.5]:
        with pytest.raises(ValueError, match='limit'):
            relation.generate(corpus, frontend, 'quota', limit=bad)


def test_retrieval_order_frontend_integrity_original_origin_and_no_labels():
    code = KEYWORD + '\ndef test_early():\n    save(dict(quantity=9))\n    assert True\n'
    corpus, frontend = fixture(code)
    for t in corpus['tests'].values():
        t['retrieval_rank'] = 0 if t['name'] == 'test_early' else 10
    expected = relation.generate(corpus, frontend, 'quantity')
    assert expected['candidates'][0]['edits'][0]['before'] == '9'
    corpus['evaluation'] = {'case': 'ignored', 'audit': 'ignored'}
    assert relation.generate(corpus, frontend, 'quantity') == expected
    altered = copy.deepcopy(corpus)
    altered['sources']['test_inputs.py']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(altered, frontend, 'quantity')
    corpus['sources']['test_inputs.py']['origin'] = 'trajectory'
    assert relation.generate(corpus, frontend, 'quantity')['candidates'] == []
    assert relation.generate({'language': 'go'}, {}, 'quantity')['status'] == 'language_unsupported'
