"""Source-only qualification before inspecting real candidate coverage."""
from __future__ import annotations

import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from prototypes.source_context_contrasts import build_catalogue, candidate_hints
from relational_gap.frontend import extract_frontend, to_emitter_corpus


PYTHON = '''def test_first():
    value = 3
    result = produce(value)
    assert result == 6

def test_second():
    value = 4
    result = produce(value)
    assert result == 8
'''
GO = '''package sample
import "testing"
func TestFirst(t *testing.T) { value:=3; result:=produce(value); if result!=6 {t.Fatal(result)} }
func TestSecond(t *testing.T) { value:=4; result:=produce(value); if result!=8 {t.Fatal(result)} }
'''
TYPESCRIPT = '''test("first",()=>{const value=3;const result=produce(value);expect(result).toBe(6);});
test("second",()=>{const value=4;const result=produce(value);expect(result).toBe(8);});
'''


def setup(code=PYTHON, language='python', path=None):
    path = path or {'python': 'test_source.py', 'go': 'source_test.go', 'typescript': 'source.test.ts'}[language]
    frontend = extract_frontend([Source(path, code, language)])
    return to_emitter_corpus(frontend), frontend


def edit(corpus, before='3', after='4', test_index=0, identifier='candidate', occurrence=0):
    test = sorted(corpus['tests'].values(), key=lambda test: test['span']['start_byte'])[test_index]
    span = test['span']; data = corpus['sources'][span['path']]['code'].encode()
    position = span['start_byte']
    for _ in range(occurrence + 1):
        begin = data.index(before.encode(), position, span['end_byte'])
        position = begin + len(before.encode())
    return dict(id=identifier, base_test_id=test['id'], imports=[], edits=[dict(
        span=dict(path=span['path'], start_byte=begin, end_byte=position), before=before, after=after)])


@pytest.mark.parametrize('language,code', [('python', PYTHON), ('go', GO), ('typescript', TYPESCRIPT)])
def test_exact_existing_input_and_different_source_expectation_yields_review_evidence(language, code):
    corpus, frontend = setup(code, language)
    catalogue = build_catalogue(corpus, frontend)
    assert catalogue['stats']['contrast_pairs'] == 1
    candidate = edit(corpus)
    original = copy.deepcopy(candidate)
    result = candidate_hints(corpus, frontend, [candidate], catalogue=catalogue)
    assert result['stats']['hinted_candidates'] == 1
    hint = result['hints'][0]
    assert hint['retained_expected']['value'] == 6
    assert hint['corresponding_expected']['value'] == 8
    assert result['oracle_correctness_proved'] is False
    assert result['candidate_ranking_unchanged'] is True
    assert candidate == original and 'edits' not in hint


def test_reverse_existing_contrast_is_symmetric_review_evidence():
    corpus, frontend = setup()
    result = candidate_hints(corpus, frontend, [edit(corpus, '4', '3', test_index=1)])
    assert len(result['hints']) == 1
    assert result['hints'][0]['retained_expected']['value'] == 8
    assert result['hints'][0]['corresponding_expected']['value'] == 6


def test_unobserved_input_cannot_borrow_or_extrapolate_an_expected_value():
    corpus, frontend = setup()
    result = candidate_hints(corpus, frontend, [edit(corpus, after='5')])
    assert result['hints'] == []
    assert result['oracle_correctness_proved'] is False


def test_same_source_expectations_are_not_a_contrast_or_a_keep_certificate():
    corpus, frontend = setup(PYTHON.replace('result == 8', 'result == 6'))
    assert build_catalogue(corpus, frontend)['pairs'] == []
    assert candidate_hints(corpus, frontend, [edit(corpus)])['hints'] == []


def test_conflicting_source_expectations_at_one_exact_input_abstain():
    conflict = PYTHON + PYTHON.split('def test_second():')[1].replace('value = 4', 'value = 4').replace('result == 8', 'result == 9')
    conflict = PYTHON + 'def test_third():' + conflict[len(PYTHON):]
    corpus, frontend = setup(conflict)
    catalogue = build_catalogue(corpus, frontend)
    assert catalogue['pairs'] == []
    assert any(row['reason'] == 'conflicting_source_expectations_at_same_input' for row in catalogue['unknowns'])
    assert candidate_hints(corpus, frontend, [edit(corpus)], catalogue=catalogue)['hints'] == []


def test_test_declaration_renaming_is_supported_without_renaming_locals():
    corpus, frontend = setup(PYTHON.replace('test_first', 'test_unusual_名字').replace('test_second', 'test_another_label'))
    assert len(build_catalogue(corpus, frontend)['pairs']) == 1
    assert len(candidate_hints(corpus, frontend, [edit(corpus)])['hints']) == 1


def test_consistent_whole_source_renaming_does_not_use_business_names():
    renamed = PYTHON.replace('produce', 'strange_operation').replace('value', '参数').replace('result', 'observed_value')
    corpus, frontend = setup(renamed)
    assert len(build_catalogue(corpus, frontend)['pairs']) == 1
    assert len(candidate_hints(corpus, frontend, [edit(corpus)])['hints']) == 1


def test_one_sided_local_alpha_rename_is_not_guessed_to_be_same_context():
    first, second = PYTHON.split('def test_second():')
    corpus, frontend = setup(first + 'def test_second():' + second.replace('value', 'other'))
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_utf8_before_and_within_test_maps_exact_source_bytes():
    code = '# 中文字节\n' + PYTHON.replace('    value =', '    note = "你好"\n    value =')
    corpus, frontend = setup(code)
    catalogue = build_catalogue(corpus, frontend)
    assert len(catalogue['pairs']) == 1
    result = candidate_hints(corpus, frontend, [edit(corpus, after='4')], catalogue=catalogue)
    assert len(result['hints']) == 1
    assert result['hints'][0]['corresponding_expected']['span']['start_byte'] > code.index('8')


@pytest.mark.parametrize('extra', ['    mutate(value)\n', '    result = produce(value)\n', '    assert value > 0\n'])
def test_extra_operation_or_assertion_in_donor_prefix_prevents_pairing(extra):
    first, second = PYTHON.split('def test_second():')
    second = second.replace('    assert result == 8', extra + '    assert result == 8')
    corpus, frontend = setup(first + 'def test_second():' + second)
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_added_candidate_operation_prevents_exact_source_hint():
    corpus, frontend = setup()
    candidate = edit(corpus)
    candidate['edits'].append(edit(corpus, '    assert result == 6', '    extra(value)\n    assert result == 6')['edits'][0])
    # This replacement includes the original oracle and is intentionally outside
    # the strict unchanged-oracle correspondence fragment.
    result = candidate_hints(corpus, frontend, [candidate])
    assert result['hints'] == []
    assert result['unknowns']


def test_real_insertion_before_assertion_keeps_role_but_cannot_match_extra_history():
    corpus, frontend = setup()
    candidate = edit(corpus)
    q = frontend['observations'][0]['assertion_span']
    candidate['edits'].append(dict(span=dict(path=q['path'], start_byte=q['start_byte']-4,
        end_byte=q['start_byte']-4), before='', after='    extra(value)\n'))
    assert candidate_hints(corpus, frontend, [candidate])['hints'] == []


def test_different_receiver_binding_is_not_normalized_by_spelling_similarity():
    code = PYTHON.replace('    result = produce(value)', '    left = Box()\n    right = Box()\n    result = left.produce(value)')
    first, second = code.split('def test_second():')
    corpus, frontend = setup(first + 'def test_second():' + second.replace('left.produce', 'right.produce'))
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_repeated_equal_assertion_text_is_bound_to_its_source_stage():
    code = '''def test_first():
    value = 3
    result = produce(value)
    assert result == 6
    result = produce(value)
    assert result == 6
def test_second():
    value = 4
    result = produce(value)
    assert result == 8
    result = produce(value)
    assert result == 8
'''
    corpus, frontend = setup(code)
    catalogue = build_catalogue(corpus, frontend)
    # The second observation includes a changed first assertion in its prefix;
    # exactly one expected hole cannot erase both observations.
    assert len(catalogue['pairs']) == 1
    result = candidate_hints(corpus, frontend, [edit(corpus)], catalogue=catalogue)
    assert len(result['hints']) == 1
    assert result['hints'][0]['observation_id'] == frontend['observations'][0]['id']


def test_changing_an_earlier_assertion_is_not_hidden_by_target_holes():
    code = PYTHON.replace('    result = produce(value)', '    assert 1 == 1\n    result = produce(value)')
    first, second = code.split('def test_second():')
    corpus, frontend = setup(first + 'def test_second():' + second.replace('assert 1 == 1', 'assert 2 == 2'))
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_different_checker_and_projection_prevent_source_pairing():
    for replacement in ['result != 8', 'other == 8']:
        corpus, frontend = setup(PYTHON.replace('result == 8', replacement))
        assert build_catalogue(corpus, frontend)['pairs'] == []


def test_second_unmasked_argument_difference_cannot_be_a_one_input_contrast():
    code = PYTHON.replace('produce(value)', 'produce(value, 10)')
    first, second = code.split('def test_second():')
    corpus, frontend = setup(first + 'def test_second():' + second.replace('value, 10', 'value, 11'))
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_distinct_lexical_class_scopes_do_not_match():
    code = 'class TestA:\n' + ''.join('    '+line+'\n' for line in PYTHON.split('def test_second():')[0].splitlines())
    code += 'class TestB:\n    def test_second():\n' + ''.join('    '+line+'\n' for line in PYTHON.split('def test_second():')[1].splitlines() if line)
    corpus, frontend = setup(code)
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_same_spelling_in_distinct_source_files_is_not_a_shared_scope():
    first, second = PYTHON.split('def test_second():')
    frontend = extract_frontend([Source('test_one.py', first, 'python'), Source('test_two.py', 'def test_second():'+second, 'python')])
    corpus = to_emitter_corpus(frontend)
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_unknown_expected_expression_and_missing_roles_do_not_become_literals():
    corpus, frontend = setup(PYTHON.replace('result == 8', 'result == expected()'))
    assert build_catalogue(corpus, frontend)['pairs'] == []
    for mutation in ['observed', 'expected']:
        corrupted = copy.deepcopy(frontend)
        corrupted['observations'][0][mutation] = None
        assert build_catalogue(corpus, corrupted)['pairs'] == []


def test_frontend_source_role_mismatch_is_explicit_unknown():
    corpus, frontend = setup()
    frontend['observations'][0]['expected']['text'] = '99'
    catalogue = build_catalogue(corpus, frontend)
    assert catalogue['pairs'] == []
    assert any(row['reason'] == 'frontend_literal_source_mismatch' for row in catalogue['unknowns'])


def test_parameter_rows_and_scripts_are_explicitly_outside_fragment():
    corpus, frontend = setup()
    first = next(iter(corpus['tests'].values()))
    first['parameter_rows'] = [[3], [4]]
    assert build_catalogue(corpus, frontend)['pairs'] == []
    first['parameter_rows'] = []
    first['owner_kind'] = 'module_script'
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_container_literals_are_not_closed_scalar_holes():
    corpus, frontend = setup(PYTHON.replace('value = 3', 'value = [3]').replace('value = 4', 'value = [4]'))
    # Inner scalars may be literal inputs, but the changed list shape must remain
    # in the full prefix; no container-as-a-scalar assumption is made.
    catalogue = build_catalogue(corpus, frontend)
    assert all(type(point['input']['value']) is not list for point in catalogue['points'])


def test_equal_typed_literal_values_do_not_create_numeric_representation_contrasts():
    corpus, frontend = setup(PYTHON.replace('value = 4', 'value = 0x3').replace('result == 8', 'result == 0x6'))
    assert build_catalogue(corpus, frontend)['pairs'] == []


def test_changed_expected_or_added_import_cannot_be_a_retained_source_hint():
    corpus, frontend = setup()
    candidate = edit(corpus)
    candidate['edits'].append(edit(corpus, '6', '8')['edits'][0])
    assert candidate_hints(corpus, frontend, [candidate])['hints'] == []
    imported = edit(corpus)
    imported['imports'] = [dict(name='produce', module='elsewhere', imported_name='produce')]
    assert candidate_hints(corpus, frontend, [imported])['hints'] == []


def test_stale_catalogue_cannot_be_used_with_changed_source():
    corpus, frontend = setup()
    catalogue = build_catalogue(corpus, frontend)
    changed = copy.deepcopy(corpus)
    changed['sources']['test_source.py']['code'] += '\n'
    with pytest.raises(ValueError, match='catalogue changed'):
        candidate_hints(changed, frontend, [edit(corpus)], catalogue=catalogue)


def test_input_order_and_evaluation_annotations_do_not_change_evidence():
    corpus, frontend = setup()
    candidates = [edit(corpus), edit(corpus, after='5', identifier='unseen')]
    expected = candidate_hints(corpus, frontend, candidates)
    decorated = copy.deepcopy(candidates)
    for candidate in decorated:
        candidate.update(evaluation={'target': True}, oracle_cache={'answer': '8'}, runtime_outcome='FAIL')
    assert candidate_hints(corpus, frontend, list(reversed(decorated))) == expected
    json.dumps(build_catalogue(corpus, frontend))
    json.dumps(expected)


def test_prefix_budget_is_explicit_unknown_not_silent_acceptance():
    corpus, frontend = setup()
    catalogue = build_catalogue(corpus, frontend, max_prefix_nodes=1)
    assert catalogue['pairs'] == []
    assert all(row['reason'] == 'prefix_node_budget' for row in catalogue['unknowns'])


def test_caller_owned_objects_are_not_mutated_by_catalogue_or_hints():
    corpus, frontend = setup()
    candidate = edit(corpus)
    snapshot = copy.deepcopy((corpus, frontend, candidate))
    catalogue = build_catalogue(corpus, frontend)
    before = copy.deepcopy(catalogue)
    candidate_hints(corpus, frontend, [candidate], catalogue=catalogue)
    assert (corpus, frontend, candidate) == snapshot
    assert catalogue == before
