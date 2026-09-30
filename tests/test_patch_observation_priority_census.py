import copy

import pytest

from scripts.census_patch_observation_priority import (
    evidence_counts,fixed_programs,project_eligibility,validate_ranking)


def candidate(identity):
    return dict(id=identity,base_test_id='test',edits=[])


def result(ids,budget=2):
    return dict(ranking=[dict(id=identity,rank=i+1) for i,identity in enumerate(ids)],
        selected=[candidate(identity) for identity in ids[:budget]])


def test_raw_prefix_keeps_uneditable_and_unknown_members_in_denominator():
    candidates=[candidate(identity) for identity in ['a','b','c']]
    ranked=result(['b','a','c'])
    assert validate_ranking(ranked,candidates,2)==['b','a']
    eligibility=[dict(id='a',eligible=True,status='source_inventory'),
        dict(id='b',eligible=False,status='source_inventory'),
        dict(id='c',eligible=False,status='unknown_inventory')]
    projected=project_eligibility(ranked['ranking'],eligibility,2)
    assert projected['selected_ids']==['a'] and projected['eligible_count']==1
    assert projected['inventory_unknown_count']==1
    assert projected['complete_ranking']==[dict(id='a',rank=1,raw_rank=2)]


@pytest.mark.parametrize('damage',['missing','duplicate','wrong_rank','skip_selected'])
def test_ranker_cannot_silently_drop_or_replace_members(damage):
    candidates=[candidate(identity) for identity in ['a','b','c']]
    ranked=result(['a','b','c'])
    if damage=='missing':ranked['ranking'].pop()
    elif damage=='duplicate':ranked['ranking'][-1]['id']='a'
    elif damage=='wrong_rank':ranked['ranking'][-1]['rank']=2
    else:ranked['selected']=[candidate('a'),candidate('c')]
    with pytest.raises(ValueError):validate_ranking(ranked,candidates,2)


def test_eligibility_projection_is_shared_and_complete_before_selection():
    eligibility=[dict(id='a',eligible=False,status='source_inventory'),
        dict(id='b',eligible=True,status='source_inventory'),
        dict(id='c',eligible=True,status='source_inventory')]
    left=project_eligibility(result(['a','b','c'])['ranking'],eligibility,1)
    right=project_eligibility(result(['c','a','b'])['ranking'],eligibility,1)
    assert left['eligible_count']==right['eligible_count']==2
    assert left['selected_ids']==['b'] and right['selected_ids']==['c']
    with pytest.raises(ValueError):project_eligibility(result(['a','b','c'])['ranking'],eligibility[:-1],1)


def test_source_programs_recover_preprobe_edits_without_mutation():
    raw=candidate('a');raw.update(instrumentation=dict(status='instrumented'),
        edits=[dict(after='logger(); input()')],program_edits=[dict(after='input()')])
    original=copy.deepcopy(raw)
    assert fixed_programs([raw])[0]['edits']==[dict(after='input()')]
    assert raw==original


@pytest.mark.parametrize('change',[dict(semantic_revision=True),dict(is_source_profile=True),
    dict(edits=[dict(role='semantic_expected')]),dict(program_edits=[dict(role='semantic_expected')])])
def test_posthoc_oracle_or_profile_cannot_enter_fixed_pool(change):
    raw=candidate('a');raw.update(change)
    with pytest.raises(ValueError,match='fixed_source_cohort'):fixed_programs([raw])


def test_duplicate_original_ids_are_not_deduplicated_into_smaller_pool():
    with pytest.raises(ValueError,match='duplicate'):fixed_programs([candidate('a'),candidate('a')])


def test_source_evidence_counts_distinguish_may_from_strict_without_truth_labels():
    rows=[dict(id='a',evidence=dict(strong_priority=True,may_priority=True,witnesses=[{}],
        unknowns=['heap:unsupported'],patch_unknowns=[])),
        dict(id='b',evidence=dict(may_priority=True,may_witnesses=[{},{}],
            unknowns=[dict(reason='heap')],patch_unknowns=['deleted_path:x'])),
        dict(id='c')]
    counts=evidence_counts(rows,['b','c'])
    assert counts['strong_candidates']==1 and counts['strong_selected']==0
    assert counts['may_candidates']==2 and counts['may_selected']==1
    assert counts['may_only_candidates']==1 and counts['may_only_selected']==1
    assert counts['strong_witness_instances']==1 and counts['may_witness_instances']==2
    assert counts['unknown_reason_instances']==dict(heap=2,deleted_path=1)
