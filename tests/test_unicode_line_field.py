import ast
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import absence_null, oracle
from relation_search import unicode_line_field as relation
from relation_search import unicode_line_field_review as review


CODE = '''import pytest
from api import consume

@pytest.mark.parametrize("payload", [
    {"message": "α", "count": 1},
    {"message": "β", "count": 2},
])
def test_text(payload):
    result = consume(payload)
    assert result is not None
    assert isinstance(result, dict)
'''


def fixture(code=CODE, *, path='test_text.py', origin='repository'):
    frontend = extract_frontend([Source(path, code, 'python', origin)])
    corpus = to_emitter_corpus(frontend)
    for rank, test in enumerate(corpus['tests'].values()):
        test['retrieval_rank'] = rank
    return corpus, frontend


def generate(code=CODE, issue='message contains user text', **kwargs):
    corpus, frontend = fixture(code, **kwargs)
    before = copy.deepcopy((corpus, frontend))
    result = relation.generate(corpus, frontend, issue)
    assert before == (corpus, frontend)
    return result, corpus, frontend


def test_one_field_edit_preserves_complete_utf8_test_decorators_rows_and_control():
    result, corpus, _ = generate()
    assert result['total_candidates'] == 2
    candidate = result['candidates'][0]
    edit = candidate['edits'][0]
    assert edit['before'] == '"α"' and edit['after'] == repr('α\u2028')
    assert ast.literal_eval(edit['after']) == 'α\u2028'
    original = candidate['source_evidence']['original_test']
    raw = corpus['sources']['test_text.py']['code'].encode()
    assert raw[edit['span']['start_byte']:edit['span']['end_byte']].decode() == edit['before']
    modified = oracle.preview(corpus, candidate).encode()
    offset = edit['span']['start_byte'] - original['start_byte']
    assert modified == (original['text'].encode()[:offset] + edit['after'].encode()
        + original['text'].encode()[offset+len(edit['before'].encode()):])
    assert original['text'].startswith('@pytest.mark.parametrize')
    assert modified.decode().endswith('assert isinstance(result, dict)')
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    emitted = output['files']['test_text.py']
    assert original['text'] in emitted
    changed = [n for n in ast.parse(emitted).body if isinstance(n, ast.FunctionDef)
               and n.decorator_list and ast.literal_eval(n.decorator_list[0].args[1])[0]['message'] == 'α\u2028']
    assert len(changed) == 1
    assert ast.dump(changed[0].body[-1]) == ast.dump(ast.parse(CODE).body[-1].body[-1])
    assert '"message": "β"' in emitted
    evidence = candidate['source_evidence']
    assert evidence['content_equivalence_claimed'] is False
    assert evidence['field_domain_established'] is False
    assert 'null_illegality_established' not in evidence
    assert candidate['generator'] == relation.VERSION
    assert candidate['operator'] == 'append_unicode_line_separator_to_source_string_field'


@pytest.mark.parametrize('statement,container', [
    ('consume({"message": ""})', 'dictionary_literal'),
    ('consume(dict(message="text"))', 'builtin_dict_keyword'),
    ('payload = {}\n    payload["message"] = "text"\n    consume(payload)', 'subscript_assignment'),
])
def test_supported_scalar_field_grammar(statement, container):
    code = 'from api import consume\ndef test_text():\n    '+statement+'\n    assert True\n'
    result, _, _ = generate(code)
    assert len(result['candidates']) == 1
    assert result['catalog'][0]['container_kind'] == container


@pytest.mark.parametrize('value', ['None', '1', '-1', 'True', '1.5', 'b"text"', 'f"text"', '"a" + "b"', 'str(1)'])
def test_only_closed_string_ast_constants_are_selected(value):
    code = 'from api import consume\ndef test_text():\n    consume({"message": '+value+'})\n    assert True\n'
    assert not generate(code)[0]['candidates']


@pytest.mark.parametrize('code', [
    'from api import consume\ndef test_x():\n    assert consume() == {"message": "a"}\n',
    'from api import consume\ndef test_x():\n    payload = {"message": "a"}\n    alias = payload\n    assert consume() == alias\n',
    'from api import consume\ndef test_x():\n    payload = {"message": "a"}\n    payload = {}\n    consume(payload)\n    assert True\n',
    'from api import consume\ndef test_x():\n    payload = {"message": "a"}\n    payload["other"] = 1\n    consume(payload)\n    assert True\n',
    'from api import consume\ndef test_x(consume):\n    consume({"message": "a"})\n    assert True\n',
    'from api import consume, dict\ndef test_x():\n    consume(dict(message="a"))\n    assert True\n',
    'from api import consume\ndef test_x():\n    payload = {"message": "a"}\n    callback = lambda: consume(payload)\n    assert callback()\n',
])
def test_expected_dependencies_aliases_shadowing_rebinding_and_capture_abstain(code):
    assert not generate(code)[0]['candidates']


def test_original_expected_role_binder_is_retained_for_parametrization():
    code = CODE.replace('result = consume(payload)', 'expected = consume(payload)').replace(
        'assert result is not None\n    assert isinstance(result, dict)', 'assert actual() == expected')
    result, _, _ = generate(code)
    assert not result['candidates']
    assert any(s['reason'] == 'source_expected_value_dependency' for s in result['skipped'])


def test_fixed_source_order_cap_and_private_reuse_do_not_depend_on_task_identity():
    code = 'from other import inspect\ndef test_renamed():\n'
    code += ''.join('    inspect({"description": '+repr(str(i))+'})\n' for i in range(20))
    code += '    assert True\n'
    before = absence_null.generate.__globals__['_scalar'], absence_null.VERSION
    result, corpus, frontend = generate(code, 'description contains text', path='elsewhere/test_values.py')
    assert result['total_candidates'] == 20 and result['selected'] == 16
    assert [ast.literal_eval(c['edits'][0]['before']) for c in result['candidates']] == [str(i) for i in range(16)]
    assert before == (absence_null.generate.__globals__['_scalar'], absence_null.VERSION)
    corpus['evaluation'] = {'case': 'irrelevant', 'audit': 'irrelevant'}
    assert relation.generate(corpus, frontend, 'description contains text') == result
    for limit in [17, -1, True, 1.5]:
        with pytest.raises(ValueError, match='limit'):
            relation.generate(corpus, frontend, 'description', limit=limit)


def test_repository_only_complete_identifier_and_source_integrity_boundaries():
    assert not generate(issue='messages')[0]['candidates']
    assert not generate(origin='trajectory')[0]['candidates']
    corpus, frontend = fixture()
    corpus = copy.deepcopy(corpus)
    corpus['sources']['test_text.py']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(corpus, frontend, 'message')
    corpus, frontend = fixture()
    next(iter(corpus['tests'].values()))['span']['end_byte'] -= 3
    result = relation.generate(corpus, frontend, 'message')
    assert result['skipped'][0]['reason'] == 'incomplete_original_test_span'
    assert not result['candidates']
    assert relation.generate({'language': 'go'}, {}, 'message')['status'] == 'language_unsupported'


def test_reference_semantics_json_validity_and_line_partition_are_distinct():
    # Only Python's standard library is exercised. No target program runs.
    value = 'sample' + relation.SUFFIX
    encoded = json.dumps({'message': value}, ensure_ascii=False)
    assert '\u2028' in encoded and '\\u2028' not in encoded
    assert json.loads(encoded) == {'message': value}
    assert len(encoded.split('\n')) == 1 and len(encoded.splitlines()) == 2
    assert json.loads(json.dumps({'message': value}, ensure_ascii=True)) == {'message': value}
    assert value != 'sample'


def test_review_retains_full_tests_adds_facts_and_never_asserts_field_validity():
    result, corpus, frontend = generate()
    candidate = result['candidates'][0]
    prepared = review.prepare(corpus, frontend, candidate, 'message accepts user text')
    request = prepared['request']
    assert request is not None
    payload = json.loads(request['prompt'])
    assert payload['unicode_line_field_reference'] == review.REFERENCE
    assert payload['original_test'] == candidate['source_evidence']['original_test']['text']
    assert payload['modified_test'] == oracle.preview(corpus, candidate)
    assert payload['modified_test'].endswith('assert isinstance(result, dict)')
    assert request['id'] == review.whole_test._identity(request)
    assert prepared['truncated'] is False
    assert review.prepare(corpus, frontend, candidate, 'message accepts text', max_prompt_bytes=10)['request'] is None
    changed = copy.deepcopy(request)
    changed['prompt'] = json.dumps(dict(payload, unicode_line_field_reference={}))
    assert review.decide(changed, '{}')['reason'] == 'unicode_reference_missing_or_changed'


def test_review_facts_do_not_turn_a_model_unknown_into_support(monkeypatch):
    result, corpus, frontend = generate()
    request = review.prepare(corpus, frontend, result['candidates'][0], 'message is restricted')['request']
    monkeypatch.setattr(review.whole_test, 'decide', lambda *a, **k:
        dict(status='unknown', alarm_eligible=False, reason='field domain unproved'))
    assert review.decide(request, '{}')['status'] == 'unknown'
