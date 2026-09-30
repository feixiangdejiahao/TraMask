from copy import deepcopy

import pytest

from scripts.study_go_comparison_profiles import closed_integer, probe_files, select_candidates


@pytest.mark.parametrize('text', ['0', '19', '-12', '+8', '0xff', '0b101', '1_000', ' 42 '])
def test_closed_integer_source_expressions(text):
    assert closed_integer(text)


@pytest.mark.parametrize('text', [None, '', '1.0', 'f()', 'n', '1+2', '(1)', '1;', '1\nvar b=2', '1 // comment', '"12"'])
def test_does_not_promote_non_literal_source(text):
    assert not closed_integer(text)


def example():
    code = 'package renamed\nfunc TestCheck(t *testing.T) {\n // π\n v := compute(9)\n if v != 8 { t.Fatal(v) }\n}\n'
    start = code.encode().index(b'9')
    end = code.encode().rindex(b'}') + 1
    corpus = dict(language='go', sources={'renamed_test.go': dict(code=code)},
                  tests={'test': dict(span=dict(path='renamed_test.go', start_byte=16, end_byte=end))})
    candidate = dict(id='example', base_test_id='test', imports=[], edits=[dict(role='input', before='9', after='20',
        span=dict(path='renamed_test.go', start_byte=start, end_byte=start + 1))])
    return corpus, candidate


def test_uniform_exact_utf8_selection_is_nonmutating():
    corpus, candidate = example()
    before = deepcopy((corpus, candidate))
    result = select_candidates(corpus, [candidate])
    assert result['selected'] == [candidate]
    assert (corpus, candidate) == before


@pytest.mark.parametrize('change', ['stale', 'outside', 'imports', 'expected', 'extra', 'missing_test', 'unchanged'])
def test_selection_rejects_non_exact_or_non_input_edits(change):
    corpus, candidate = example()
    edit = candidate['edits'][0]
    if change == 'stale':
        edit['before'] = '7'
    elif change == 'outside':
        edit['span']['end_byte'] = len(corpus['sources']['renamed_test.go']['code'].encode()) + 4
    elif change == 'imports':
        candidate['imports'] = ['new/pkg']
    elif change == 'expected':
        edit['role'] = 'expected'
    elif change == 'extra':
        candidate['edits'].append(deepcopy(edit))
    elif change == 'missing_test':
        candidate['base_test_id'] = 'missing'
    else:
        edit['after'] = edit['before']
    assert not select_candidates(corpus, [candidate])['selected']


def test_limit_retains_unselected_denominator_and_ignores_input_order():
    corpus, candidate = example()
    rows = [dict(deepcopy(candidate), id=str(i)) for i in range(10)]
    result = select_candidates(corpus, rows, limit=3)
    reverse = select_candidates(corpus, list(reversed(rows)), limit=3)
    assert result == reverse
    assert result['eligible_count'] == 10
    assert len(result['selected']) == 3 and len(result['unselected']) == 7


def test_duplicate_ids_are_not_silently_removed():
    corpus, candidate = example()
    with pytest.raises(ValueError, match='duplicate_eligible'):
        select_candidates(corpus, [candidate, deepcopy(candidate)])


def test_other_languages_remain_explicitly_unsupported():
    corpus, candidate = example()
    corpus['language'] = 'python'
    assert select_candidates(corpus, [candidate])['status'] == 'unsupported_language'


def test_mount_only_instrumented_production_not_original_test_files():
    record = dict(comparisons=[dict(original_span=dict(path='production.go'))],
        files={'production.go': 'instrumented', 'original_test.go': 'original tests'},
        runtime_files={'helper.go': 'helper'})
    assert probe_files(record) == {'production.go': 'instrumented', 'helper.go': 'helper'}
