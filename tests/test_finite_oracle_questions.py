"""Lossless query presentation and explicit per-member oracle coverage."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from experimental.finite_oracle_questions import (SYSTEM, build_question,
    factor_evidence, restore_evidence, validate_question)
from relation_search.oracle import prepare_requests
from relation_search.instrument import instrument_candidates
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def setup():
    code = '''def twice(value):
    """A pure helper whose complete declaration is available to the oracle.
    The finite alternatives change its argument, and the output doubles it.
    """
    return value * 2

def test_case():
    answer = twice(2)
    assert answer == 4
    stable = 7
    assert stable == 7
'''
    front = extract_frontend([Source('test_case.py', code, 'python')])
    corpus = to_emitter_corpus(front)
    base = next(iter(corpus['tests']))
    begin = code.encode().index(b'twice(2)') + len(b'twice(')
    rows = [dict(id='input_'+str(value), base_test_id=base, imports=[], edits=[dict(
        span=dict(path='test_case.py', start_byte=begin, end_byte=begin+1),
        before='2', after=str(value), role='input')]) for value in (2,3)]
    return corpus, front, rows


def test_two_forms_have_exactly_the_same_members_and_all_other_facts():
    corpus, front, rows = setup()
    a = build_question(corpus,front,rows,'The helper doubles its argument.',representation='template')
    b = build_question(corpus,front,rows,'The helper doubles its argument.',representation='expanded')
    assert a['offered'] == b['offered']
    assert a['analysis_evidence'] == b['analysis_evidence']
    assert a['system'] == b['system'] == SYSTEM
    pa,pb = json.loads(a['prompt']),json.loads(b['prompt'])
    source=pa.pop('test_source');expanded=pb.pop('test_source')
    pa.pop('representation');pb.pop('representation')
    assert pa == pb
    for variant, full in zip(source['variants'],expanded):
        pieces=[]
        for segment,replacement in zip(source['segments'],variant['replacements']):
            pieces.extend([segment,replacement['after']])
        pieces.append(source['segments'][-1])
        assert ''.join(pieces) == full['modified_test']
    assert '{"revisions":' not in SYSTEM
    assert '{"results":' in SYSTEM


def test_complete_rendered_evidence_can_be_reconstructed_without_losing_bindings():
    corpus,front,rows=setup()
    request=build_question(corpus,front,rows,'Double each argument.')
    payload=json.loads(request['prompt'])
    assert payload['shared_code']
    for index,member in enumerate(payload['variants']):
        expected=request['analysis_evidence']['C'+str(index)]['rendered']
        assert restore_evidence(member['dependency_evidence']['rendered'],payload['shared_code'])==expected


def test_keep_and_revision_are_bound_to_the_correct_finite_member():
    corpus,front,rows=setup();request=build_question(corpus,front,rows,'Double each argument.')
    response=dict(results=[
        dict(candidate='C0',status='keep',updates=[],basis='2 doubles to 4'),
        dict(candidate='C1',status='revise',updates=[dict(assertion='A0',code='assert answer == 6')],basis='3 doubles to 6')])
    result=validate_question(request,response,corpus)
    assert result['all_members_answered']
    assert [r['status'] for r in result['members']]==['keep','revise']
    assert len(result['revisions'])==1
    assert result['revisions'][0]['semantic_revision']['parent']=='input_3'
    assert result['revisions'][0]['edits'][-1]['after']=='assert answer == 6'
    assert all(r['semantic_correctness']=='unreviewed' for r in result['members'])


def test_unknown_and_omission_never_become_keep():
    corpus,front,rows=setup();request=build_question(corpus,front,rows,'Double each argument.')
    result=validate_question(request,dict(results=[dict(candidate='C0',status='unknown',updates=[],basis='insufficient contract')]),corpus)
    assert [r['status'] for r in result['members']]==['unknown','unanswered']
    assert not result['all_members_answered'] and not result['revisions']


def test_duplicate_or_wrong_actual_answer_cannot_be_accepted():
    corpus,front,rows=setup();request=build_question(corpus,front,rows,'Double each argument.')
    duplicate=validate_question(request,dict(results=[dict(candidate='C0',status='keep',updates=[],basis='a')]*2),corpus)
    assert duplicate['members'][0]['status']=='duplicate_answer'
    wrong=validate_question(request,dict(results=[dict(candidate='C1',status='revise',updates=[dict(assertion='A0',code='assert stable == 6')],basis='a')]),corpus)
    assert wrong['members'][1]['status']=='rejected_structure'
    assert not wrong['revisions']


@pytest.mark.parametrize('payload',[None,[],{'results':None},{'results':[]},{'results':[{'candidate':[]}]}])
def test_malformed_or_empty_output_has_no_implicit_coverage(payload):
    corpus,front,rows=setup();request=build_question(corpus,front,rows,'Double each argument.')
    result=validate_question(request,payload,corpus)
    assert not result['all_members_answered'] and result['answered_members']==0
    assert not result['revisions']


def test_exact_source_blocks_do_not_assume_equal_provenance_or_behavior():
    body='x'*160
    values=[dict(rendered='first origin\n'+body,declarations=[dict(code=body)]),
            dict(rendered='second origin\n'+body,declarations=[dict(code=body)])]
    shared,rendered=factor_evidence(values)
    assert len(shared)==1
    assert rendered[0]!=rendered[1]
    assert [restore_evidence(text,shared) for text in rendered]==[v['rendered'] for v in values]


def test_past_oracle_answers_are_rejected_as_new_question_inputs():
    corpus,front,rows=setup();rows[0]['semantic_revision']={'parent':'past'}
    with pytest.raises(ValueError,match='historical oracle'):
        build_question(corpus,front,rows,'Double each argument.')


@pytest.mark.parametrize('payload', ['not JSON', '{"results":', '{"results": [] trailing}', ''])
def test_invalid_json_is_an_explicit_unanswered_result(payload):
    corpus, front, rows = setup()
    request = build_question(corpus, front, rows, 'Double each argument.')
    result = validate_question(request, payload, corpus)
    assert result['error'] == 'invalid_member_results'
    assert [row['status'] for row in result['members']] == ['invalid_answer', 'invalid_answer']
    assert result['answered_members'] == 0 and not result['revisions']


@pytest.mark.parametrize('code', [None, [], {}, 3, True])
def test_nontext_assertion_code_invalidates_only_its_own_member(code):
    corpus, front, rows = setup()
    request = build_question(corpus, front, rows, 'Double each argument.')
    result = validate_question(request, dict(results=[
        dict(candidate='C0', status='revise', updates=[dict(assertion='A0', code=code)], basis='bad code'),
        dict(candidate='C1', status='keep', updates=[], basis='valid independent hypothesis')]), corpus)
    assert [member['status'] for member in result['members']] == ['invalid_answer', 'keep']
    assert result['answered_members'] == 1 and not result['revisions']


def test_normal_runtime_probes_do_not_count_as_historical_oracle_inputs():
    corpus, front, rows = setup()
    candidate = rows[0]
    assertion = next(row for row in front['observations'] if row['kind']=='assertion'
                     and row['test_id']==candidate['base_test_id'])
    candidate['runtime_probes'] = [dict(insert_before=assertion['assertion_span'], phase='observation',
        roles=[dict(name='result', expression='answer', origin_span=assertion['observed']['span'])])]
    instrumented = instrument_candidates(corpus, [candidate])
    generated = next(row for row in instrumented['candidates'] if row['id']==candidate['id'])
    assert generated['instrumentation']['status'] == 'instrumented'
    assert generated['edits'] != generated['program_edits']
    assert any(edit['role']=='relation_runtime_probe' for edit in generated['edits'])
    request = build_question(corpus, front, [generated], 'Double each argument.')
    result = validate_question(request, dict(results=[dict(candidate='C0', status='keep', updates=[],
        basis='The complete source-only test is still valid.')]), corpus)
    assert result['all_members_answered'] and result['members'][0]['status'] == 'keep'
