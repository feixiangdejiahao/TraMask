import copy

import pytest

from scripts.census_helper_expected_slots import compare_slots,select_source_members,sha_order


def ordinary(editable):
    return dict(editable=editable,reason=None if editable else 'unsupported_by_existing_guard')


def row(kind,editable,reason=None):
    return dict(kind=kind,editable=editable,reason=reason)


def test_helper_support_is_counted_separately_from_ordinary_assertions():
    base=[ordinary(False),ordinary(True)]
    extended=[
        row('ordinary_assertion',False,'unsupported_by_existing_guard'),
        row('ordinary_assertion',True),row('helper_expected_call',True),
        row('helper_expected_call',False,'expected_not_scalar_literal')]
    unchanged=copy.deepcopy(extended)
    result=compare_slots('c',base,extended)
    assert result['ordinary_editable']==1 and result['helper_editable']==1
    assert result['extended_editable']==2 and result['helper_calls']==2
    assert not result['extension_only_eligible'] and not result['ordinary_count_changed']
    assert result['unknown_reasons']['expected_not_scalar_literal']==1
    assert extended==unchanged


def test_only_helper_support_counts_as_extension_only_eligibility():
    result=compare_slots('c',[ordinary(False)],[
        row('ordinary_assertion',False),row('helper_expected_call',True)])
    assert result['extension_only_eligible'] and result['extended_eligible']
    ordinary_change=compare_slots('c',[ordinary(False)],[row('ordinary_assertion',True)])
    assert ordinary_change['ordinary_editable_changed']
    assert ordinary_change['extended_eligible'] and not ordinary_change['extension_only_eligible']


def test_unknown_helper_and_non_go_leave_support_denominators_explicit():
    result=compare_slots('c',[ordinary(False)],[
        row('ordinary_assertion',False),row('helper_expected_call',False,'unresolved')])
    assert result['helper_calls']==1 and result['helper_editable']==0
    assert not result['extended_eligible'] and result['extended_status']=='source_inventory'
    assert compare_slots('c',[ordinary(True)])['extended_status']=='not_go'
    with pytest.raises(ValueError,match='kind'):
        compare_slots('c',[],[row('unknown_kind',True)])


def test_source_selection_is_stable_and_does_not_use_outcomes_or_case_names():
    rows=[dict(candidate_id=name,helper_editable=1,extended_eligible=True,target_hit=False)
        for name in ['a','b','c','d']]
    expect=[r['candidate_id'] for r in sorted(rows,key=lambda r:sha_order(r['candidate_id']))[:2]]
    assert select_source_members(rows)['candidate_ids']==expect
    flipped=[dict(r,target_hit=True) for r in reversed(rows)]
    assert select_source_members(flipped)['candidate_ids']==expect
    fallback=[dict(candidate_id='x',helper_editable=0,extended_eligible=True)]
    assert select_source_members(fallback)['selection_class']=='ordinary_fallback'
    assert select_source_members([])['candidate_ids']==[]
