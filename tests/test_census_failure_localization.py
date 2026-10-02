"""Authored source and receipt fixtures; no subject execution or evaluation truth."""
import ast
import copy
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.compact_test_obligations import analyze
from scripts.census_failure_localization import (
    attach_q, controlled_failures, emitted_files, locate, locations,
    normalize_owner, process, sample,
)


def localized(normalized, emitted=None, *, lines=None, detail=None, parameterized=False):
    emitted = emitted or normalized.replace('test_original', 'test_clone')
    path = 'tests/test_example.py'
    tree = ast.parse(normalized)
    root = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == 'test_original')
    if detail is None:
        if lines is None:
            lines = [next(node for node in ast.walk(ast.parse(emitted)) if isinstance(node, ast.Assert)).lineno]
        detail = '\n'.join(f'{path}:{line}: AssertionError' for line in lines)
    return locate(detail, {path: emitted}, 'test_clone', (path, normalized, tree), root, parameterized=parameterized)


def test_baseline_decoder_never_decodes_other_values(monkeypatch):
    text = '{"review_labels": {"payload": "ignored ] } \\\" nested"}, "controlled_failures": [{"key":"a"}], "positives":[{"x":1}]}'
    original = json.loads
    decoded = []

    def watched(value, *args, **kwargs):
        decoded.append(value)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(json, 'loads', watched)
    assert controlled_failures(text) == [{'key': 'a'}]
    assert decoded == ['[{"key":"a"}]']
    with pytest.raises(ValueError, match='duplicate'):
        controlled_failures('{"controlled_failures":[],"controlled_failures":[]}')


def test_sample_is_frozen_by_source_identity_not_outcomes_or_order():
    records = [dict(case='C', candidate_id=str(i), key=f'C:0:{i}', native_evidence=['secret']) for i in range(20)]
    chosen, count = sample(records, 7)
    changed = [dict(row, native_evidence=['different']) for row in reversed(records)]
    assert count == 20
    assert [row['key'] for row in chosen] == [row['key'] for row in sample(changed, 7)[0]]
    assert len(sample(records + records, 100)[0]) == 20


def test_direct_assert_maps_through_renamed_instrumented_snapshot():
    code = 'def test_original():\n    value = subject("猫")\n    assert value == 1\n    assert later() == 2\n'
    emitted = '# generated copy\n' + code.replace('test_original', 'test_clone').replace(
        '    assert value', '    try:\n        record_probe()\n    except Exception:\n        pass\n    assert value')
    line = next(n.lineno for n in ast.walk(ast.parse(emitted)) if isinstance(n, ast.Assert))
    result = localized(code, emitted, lines=[line])
    assert result['status'] == 'localized_root_assertion'
    assert result['statement'] == 'assert value == 1'
    assert result['emitted_assertion']['line'] > result['normalized_assertion']['line']
    assert 'record_probe' not in result['prefix']['code']
    assert 'later()' not in result['prefix']['code']
    assert not result['first_failure_proved'] and not result['causal_prefix_proved']
    assert result['complete_test_validity'] == 'unassessed'


def test_assertion_message_text_never_enters_source_question():
    code = 'def test_original():\n    assert subject() == 1\n'
    result = localized(code, detail='SECRET ACTUAL VALUE\ntests/test_example.py:2: AssertionError: SECRET MESSAGE')
    source = Source('tests/test_example.py', code, 'python')
    frontend = extract_frontend([source]); corpus = to_emitter_corpus(frontend)
    candidate = dict(id='generic', base_test_id=next(iter(corpus['tests'])), edits=[], imports=[])
    graph = analyze(corpus, frontend, candidate)
    result = attach_q(result, graph)
    assert result['compact_q']['id'] == 'Q0'
    assert 'SECRET' not in json.dumps(result['source_question'])
    assert result['source_question']['later_checks'] == 'not_adjudicated'


def test_duplicate_same_assert_cannot_choose_by_ast_text():
    code = 'def test_original():\n    assert value == 1\n    assert value == 1\n'
    result = localized(code, lines=[3])
    assert result['status'] == 'unknown'
    assert result['reason'] == 'normalized_assertion_missing_or_ambiguous'


def test_two_asserts_on_one_native_line_are_ambiguous():
    code = 'def test_original():\n    assert x; assert y\n'
    result = localized(code, lines=[2])
    assert result['reason'] == 'multiple_reported_assertion_sites'


def test_helper_assert_not_misidentified_as_root_assertion():
    code = 'def helper():\n    assert value == 1\ndef test_original():\n    helper()\n'
    result = localized(code, lines=[2])
    assert result['reason'] == 'helper_or_other_test_assertion'


@pytest.mark.parametrize('code,reason', [
    ('async def test_original():\n    assert value == 1\n', 'async_root'),
    ('def test_original():\n    yield value\n    assert value == 1\n', 'async_or_generator_context'),
])
def test_async_and_generator_scopes_stay_unknown(code, reason):
    assert localized(code)['reason'] == reason


@pytest.mark.parametrize('body,unknown', [
    ('with pytest.raises(AssertionError):\n        assert value == 1', 'exception_or_context_manager_region'),
    ('try:\n        assert value == 1\n    except AssertionError:\n        pass', 'exception_or_context_manager_region'),
    ('for value in values:\n        assert value == 1', 'repeated_site_runtime_instance_unknown'),
])
def test_location_is_preserved_but_exception_or_loop_acceptance_is_not_proved(body, unknown):
    result = localized('def test_original():\n    ' + body + '\n')
    assert result['status'] == 'source_site_located_context_unknown'
    assert unknown in result['context_unknowns']
    assert 'normalized_assertion' in result
    assert not result['first_failure_proved']


def test_parameterized_instance_never_supplies_imagined_actual_bindings():
    result = localized('def test_original(value):\n    assert value == 1\n', parameterized=True)
    assert result['status'] == 'source_site_located_context_unknown'
    assert result['context_unknowns'] == ['decorator_or_runtime_parameter_context']


def test_soft_assert_adapter_and_exception_operation_are_unknown():
    code = 'def test_original():\n    check.equal(value, 1)\n'
    result = localized(code, lines=[2])
    assert result['reason'] == 'reported_location_not_a_source_assertion'
    assert not locations('tests/test_example.py:2: ValueError')


def test_absolute_receipt_path_requires_complete_unique_source_suffix():
    code = 'def test_original():\n    assert value == 1\n'
    assert localized(code, detail='/app/tests/test_example.py:2: AssertionError')['status'] == 'localized_root_assertion'
    assert localized(code, detail='/app/other/test_example.py:2: AssertionError')['status'] == 'unknown'


def test_traceback_duplicate_terminal_location_is_one_source_site():
    code = 'def test_original():\n    assert value == 1\n'
    detail = '  File "/app/tests/test_example.py", line 2, in test_clone\n    assert value == 1\ntests/test_example.py:2: AssertionError'
    assert localized(code, detail=detail)['status'] == 'localized_root_assertion'


def test_snapshot_sha_and_generated_candidate_identity_are_required(tmp_path):
    path = tmp_path / 'snapshot'
    path.write_text('def test_clone():\n    assert value == 1\n')
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = dict(obligations=[dict(candidate_id='id', id='test_clone', test_name='test_clone', path='tests/test_example.py')],
        phases=[dict(role='generated', files=[dict(target='tests/test_example.py', staged='staged', sha256=checksum)])],
        mounts=[dict(target='staged', source=str(path), sha256=checksum)])
    assert emitted_files(manifest, 'id')[1]['test_name'] == 'test_clone'
    with pytest.raises(ValueError, match='not unique'):
        emitted_files(manifest, 'different')
    path.write_text('changed')
    with pytest.raises(ValueError, match='SHA'):
        emitted_files(manifest, 'id')


def test_normalized_source_requires_exact_original_edit_bytes():
    code = 'def test_original():\n    assert value == 1\n'
    frontend = extract_frontend([Source('tests/test_example.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    start = code.index('1')
    candidate = dict(base_test_id=next(iter(corpus['tests'])), edits=[dict(
        span=dict(path='tests/test_example.py', start_byte=start, end_byte=start + 1), before='2', after='3')])
    with pytest.raises(ValueError, match='edit mismatch'):
        normalize_owner(corpus, candidate)


def test_missing_compact_q_remains_unknown_without_guessing_nearest_check():
    result = localized('def test_original():\n    assert value == 1\n')
    output = attach_q(result, dict(obligations={}, sources={}, root='V0', status='partial'))
    assert output['status'] == 'source_site_located_context_unknown'
    assert output['reason'] == 'compact_q_missing_or_ambiguous'
    assert 'source_question' not in output


def test_full_receipt_join_maps_only_declared_candidate_and_keeps_details_local(tmp_path):
    code = 'def test_original():\n    value = subject()\n    assert value == 1\n    assert later()\n'
    frontend = extract_frontend([Source('tests/test_example.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    candidate = dict(id='c', base_test_id=next(iter(corpus['tests'])), imports=[], edits=[])
    emitted = code.replace('test_original', 'test_clone')
    snapshot = tmp_path / 'emitted.snapshot'
    snapshot.write_text(emitted)
    checksum = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    manifest = dict(obligations=[dict(candidate_id='c', id='test_clone', test_name='test_clone', path='tests/test_example.py')],
        phases=[dict(role='generated', files=[dict(target='tests/test_example.py', staged='staged', sha256=checksum)])],
        mounts=[dict(target='staged', source=str(snapshot), sha256=checksum)])

    def freeze(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    native = dict(errors=[], tests=[dict(id='tests.example::test_clone', status='fail',
        detail='SECRET OUTPUT\ntests/test_example.py:3: AssertionError: SECRET FAILURE')])
    record = dict(candidate_id='c', inputs={
        'corpus': freeze('corpus.json', corpus), 'frontend': freeze('frontend.json', frontend),
        'candidates': freeze('candidates.json', [candidate])}, native_evidence=[dict(
            result=freeze('native.json', native), manifest=freeze('manifest.json', manifest), test_ids=['test_clone'])])
    result, audit = process(record, {})
    assert result['status'] == 'localized_root_assertion'
    assert result['compact_q']['id'] == 'Q0'
    assert 'SECRET' not in json.dumps(result)
    assert audit['native_receipts'][0]['diagnostic_sha256']
    assert audit['compact_graph']['sources']
    duplicated = copy.deepcopy(record)
    duplicated['native_evidence'].append(record['native_evidence'][0])
    result, _ = process(duplicated, {})
    assert result['reason'] == 'failed_runtime_instance_not_unique'


def test_same_generated_name_in_another_snapshot_cannot_claim_candidate_scope():
    code = 'def test_original():\n    assert value == 1\n'
    tree = ast.parse(code)
    result = locate('other.py:2: AssertionError', {'other.py': code.replace('test_original', 'test_clone')},
                    'test_clone', ('tests/test_example.py', code, tree), tree.body[0], candidate_path='tests/test_example.py')
    assert result['reason'] == 'assertion_outside_candidate_emitted_path'


def test_duplicate_generated_function_name_is_not_manifest_identity_proof():
    code = 'def test_original():\n    assert value == 1\n'
    emitted = code.replace('test_original', 'test_clone') + 'def test_clone():\n    assert other == 2\n'
    assert localized(code, emitted, lines=[2])['reason'] == 'generated_test_definition_not_unique'


def test_traceback_function_name_must_agree_with_emitted_source_scope():
    code = 'def test_original():\n    assert value == 1\n'
    detail = '  File "/app/tests/test_example.py", line 2, in other_function\n'
    assert localized(code, detail=detail)['reason'] == 'traceback_function_source_mismatch'
