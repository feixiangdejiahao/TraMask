"""Independent interface checks; these do not establish oracle correctness."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from experimental.finite_oracle_questions import (
    build_question, restore_evidence, validate_question,
)
from experimental.finite_oracle_templates import build_catalogue
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def scenario():
    # Identical assertion text observes the same local at different stages.
    # The last assertion is recognized but not editable by the structural guard.
    code = '''from .helpers import identity as imported_helper

def test_history():
    values = [2]
    alias = values
    value = 2
    assert value == 2
    alias.append(value)
    assert values[-1] == 2
    value = 2
    assert value == 2
    assert all(item >= 0 for item in values)
'''
    helper = '''def identity(value):
    """This declaration is deliberately long enough to exercise exact shared
    source factoring without making either origin or its contract identical.
    """
    return value
'''
    sources = [Source('pkg/test_history.py', code, 'python'),
               Source('pkg/helpers.py', helper, 'python')]
    front = extract_frontend(sources)
    corpus = to_emitter_corpus(front)
    base = next(iter(corpus['tests']))
    begin = code.encode().index(b'value = 2') + len(b'value = ')
    rows = [dict(id='variant_' + str(value), base_test_id=base,
        imports=[dict(name='donor', module='.' + module, imported_name='identity',
                      source_path='pkg/test_history.py')],
        source_test_ids=[], source_contexts=[dict(span=dict(path='pkg/helpers.py',
            start_byte=0, end_byte=len(helper.encode())))],
        edits=[dict(span=dict(path='pkg/test_history.py', start_byte=begin,
            end_byte=begin + 1), before='2', after=str(value), role='input')])
        for value, module in [(3, 'left'), (5, 'right')]]
    return corpus, front, rows


def kept(alias):
    return dict(candidate=alias, status='keep', updates=[], basis='independent hypothesis')


def test_member_imports_and_complete_evidence_remain_independent_in_both_arms():
    corpus, front, rows = scenario()
    template = build_question(corpus, front, rows, 'Preserve ordered operations.')
    expanded = build_question(corpus, front, rows, 'Preserve ordered operations.',
                              representation='expanded')
    a, b = json.loads(template['prompt']), json.loads(expanded['prompt'])
    assert a['variants'] == b['variants']
    assert a['shared_code'] == b['shared_code']
    for index, row in enumerate(rows):
        member = a['variants'][index]
        assert row['imports'][0] in member['import_bindings']
        restored = restore_evidence(member['dependency_evidence']['rendered'], a['shared_code'])
        assert restored == template['analysis_evidence']['C' + str(index)]['rendered']
        assert 'source_context' in restored or 'candidate_source_context' in restored
    assert a['variants'][0]['import_bindings'] != a['variants'][1]['import_bindings']


def test_repeated_assertion_stage_is_selected_by_identity_not_by_text():
    corpus, front, rows = scenario()
    request = build_question(corpus, front, rows, 'Assignments establish current value.')
    offered = request['offered']['C0']['assertions']
    duplicates = [(alias, assertion) for alias, assertion in offered.items()
                  if assertion['code'] == 'assert value == 2']
    assert len(duplicates) == 2
    earlier, later = duplicates
    assert earlier[1]['span']['start_byte'] < later[1]['span']['start_byte']
    outcome = validate_question(request, dict(results=[dict(candidate='C0',
        status='revise', updates=[dict(assertion=later[0], code='assert value == 7')],
        basis='This is a structural test, not a correct semantic oracle.')]), corpus)
    assert outcome['members'][0]['status'] == 'revise'
    revision, = outcome['revisions']
    edit, = [edit for edit in revision['edits'] if edit['role'] == 'semantic_expected']
    assert edit['span'] == later[1]['span']
    assert edit['span'] != earlier[1]['span']


def test_readonly_assertion_is_visible_and_cannot_be_rewritten_by_a_revision():
    corpus, front, rows = scenario()
    request = build_question(corpus, front, rows, 'Values are nonnegative.')
    full = build_catalogue(corpus, front, rows)['families'][0]['variants'][0]['assertions']
    readonly, = [assertion for assertion in full if not assertion['editable']]
    payload = json.loads(request['prompt'])
    row, = [assertion for assertion in payload['variants'][0]['assertions']
            if assertion['code'] == readonly['code']]
    assert row['code'] in ''.join(payload['test_source']['segments'])
    rejected = validate_question(request, dict(results=[dict(candidate='C0',
        status='revise', updates=[dict(assertion=row['id'], code='assert True')],
        basis='Unsupported change.'), kept('C1')]), corpus)
    assert [member['status'] for member in rejected['members']] == ['rejected_structure', 'keep']
    assert not rejected['revisions'] and not rejected['all_members_answered']


@pytest.mark.parametrize('bad_row', [
    dict(candidate='C0', status=[], updates=[], basis='invalid status type'),
    dict(candidate='C0', status={}, updates=[], basis='invalid status type'),
    dict(candidate='C0', status='revise', updates=[None], basis='invalid update item'),
    dict(candidate='C0', status='revise', updates=[[]], basis='invalid update item'),
    dict(candidate='C0', status='revise', updates=[dict(assertion=[], code='assert value == 3')], basis='invalid id type'),
    dict(candidate='C0', status='revise', updates=[dict(assertion={}, code='assert value == 3')], basis='invalid id type'),
])
def test_malformed_one_member_cannot_crash_or_destroy_other_member(bad_row):
    corpus, front, rows = scenario()
    request = build_question(corpus, front, rows, 'Assignments establish current value.')
    result = validate_question(request, dict(results=[bad_row, kept('C1')]), corpus)
    assert result['members'][0]['status'] not in {'keep', 'revise'}
    assert result['members'][1]['status'] == 'keep'
    assert result['answered_members'] == 1 and not result['all_members_answered']
    assert not result['revisions']


@pytest.mark.parametrize('bad_alias', [[], {}, 0, None, 'variant_3', 'C90'])
def test_invalid_alias_never_claims_coverage_of_a_real_member(bad_alias):
    corpus, front, rows = scenario()
    request = build_question(corpus, front, rows, 'Assignments establish current value.')
    result = validate_question(request, dict(results=[{**kept('C0'), 'candidate':bad_alias}, kept('C1')]), corpus)
    assert [member['status'] for member in result['members']] == ['unanswered', 'keep']
    assert result['answered_members'] == 1


def test_duplicate_alias_revokes_the_first_accepted_hypothesis():
    corpus, front, rows = scenario()
    request = build_question(corpus, front, rows, 'Assignments establish current value.')
    result = validate_question(request, dict(results=[kept('C0'),
        dict(candidate='C0', status='unknown', updates=[], basis='second conflicting answer')]), corpus)
    assert [member['status'] for member in result['members']] == ['duplicate_answer', 'unanswered']
    assert not result['revisions'] and result['answered_members'] == 0


def test_unchanged_revision_is_not_counted_as_completed_revision():
    corpus, front, rows = scenario()
    request = build_question(corpus, front, rows, 'Assignments establish current value.')
    alias, offered = next(iter(request['offered']['C0']['assertions'].items()))
    result = validate_question(request, dict(results=[dict(candidate='C0', status='revise',
        updates=[dict(assertion=alias, code=offered['code'])], basis='No actual change.')]), corpus)
    assert result['members'][0]['status'] == 'revision_did_not_change_expectation'
    assert result['answered_members'] == 0 and not result['revisions']


def test_modified_local_source_record_is_detected_before_validation():
    corpus, front, rows = scenario()
    request = build_question(corpus, front, rows, 'Assignments establish current value.')
    request['offered']['C0']['candidate']['imports'][0]['module'] = '.different'
    with pytest.raises(ValueError, match='offered source records changed'):
        validate_question(request, dict(results=[kept('C0')]), corpus)


def test_instrumented_source_only_snapshot_cannot_smuggle_a_past_oracle_edit():
    corpus, front, rows = scenario()
    first = rows[0]
    inventory = build_catalogue(corpus, front, rows)['families'][0]['variants'][0]['assertions']
    check = inventory[0]
    first['program_edits'] = copy.deepcopy(first['edits']) + [dict(span=check['span'],
        before=check['code'], after='assert value == 3', role='semantic_expected')]
    first['instrumentation'] = dict(status='instrumented')
    # The visible runtime edits have no semantic_expected marker; source-only
    # reasoning consumes program_edits and must reject the effective marker.
    with pytest.raises(ValueError, match='historical oracle'):
        build_question(corpus, front, [first], 'Assignments establish current value.')
