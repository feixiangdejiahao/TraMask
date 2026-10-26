"""Blind fixed-pool rank comparison; never dispatch or execute subjects."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from experimental.singleton_oracle_slots import assertion_inventory
from relation_search.instrument import _program_edits
from relation_search.oracle import program_candidate
from relation_search.semantic_selection import select as shape_select


FILES=['scripts/census_patch_observation_priority.py','tests/test_patch_observation_priority_census.py',
    'research/patch_observation_priority_protocol.md',
    'experimental/patch_observation_priority.py','tests/test_patch_observation_priority.py',
    'tests/test_patch_observation_priority_review.py',
    'relation_search/semantic_selection.py','experimental/singleton_oracle_slots.py',
    'tests/test_semantic_selection.py','tests/test_singleton_oracle_slots.py',
    'experimental/assertion_operand_guard.py','tests/test_assertion_operand_guard.py','relation_search/oracle.py',
    'relation_search/instrument.py','relation_search/runtime.py','relation_search/oracle_evidence.py',
    'experimental/source_edit_identity.py','tests/test_source_edit_identity.py',
    'experimental/modified_observation_impact.py','tests/test_modified_observation_impact.py',
    'relation_search/impact_selection.py','tests/test_impact_selection.py',
    'experimental/local_helper_evidence.py','tests/test_local_helper_evidence.py',
    'experimental/go_assertion_helper.py','tests/test_go_assertion_helper.py',
    'experimental/go_arity_guard.py','tests/test_go_arity_guard.py',
    'experimental/source_failure_evidence.py','tests/test_source_failure_evidence.py',
    'anchor_retrieval/index.py','anchor_retrieval/graph.py','anchor_retrieval/syntax.py',
    'anchor_retrieval/frontier.py','generic_composition/corpus.py','relational_gap/frontend.py',
    'anchor_retrieval/__init__.py','generic_composition/__init__.py',
    'relation_search/__init__.py','relational_gap/__init__.py']

ARM_MODES={'shape':None,'strict':'strict','may':'may'}


def read(path):return json.loads(Path(path).read_text())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def fixed_programs(candidates):
    """Reject post-hoc expectations; do not mutate the original source pool."""
    result=[]
    for raw in candidates:
        if raw.get('is_source_profile') or raw.get('semantic_revision') or any(
            edit.get('role')=='semantic_expected'
            for edit in [*_program_edits(raw),*raw.get('edits',[]),*raw.get('program_edits',[])]):
            raise ValueError('fixed_source_cohort_contains_profile_or_oracle_revision')
        result.append(program_candidate(raw))
    if len({row['id'] for row in result})!=len(result):
        raise ValueError('duplicate_source_candidate_id')
    return result


def validate_ranking(result,candidates,budget):
    """Complete ranks and raw selections share one fixed denominator."""
    expected={row['id'] for row in candidates}
    ranking=result['ranking']
    if len(ranking)!=len(expected) or {row['id'] for row in ranking}!=expected:
        raise ValueError('ranking_candidate_denominator_changed')
    if [row['rank'] for row in ranking]!=list(range(1,len(ranking)+1)):
        raise ValueError('ranking_not_contiguous_in_order')
    raw_ids=[row['id'] for row in ranking[:budget]]
    if [row['id'] for row in result['selected']]!=raw_ids:
        raise ValueError('raw_selection_does_not_match_rank_prefix')
    return raw_ids


def source_eligibility(corpus,frontend,candidates):
    """Freeze the old assertion interface independently of either ranker."""
    result=[]
    for candidate in candidates:
        try:
            rows=assertion_inventory(corpus,frontend,candidate)
            editable=sum(bool(row['editable']) for row in rows)
            result.append(dict(id=candidate['id'],status='source_inventory',eligible=editable>0,
                assertions=len(rows),editable_assertions=editable))
        except (ValueError,KeyError,IndexError,TypeError,UnicodeError) as error:
            result.append(dict(id=candidate['id'],status='unknown_inventory',eligible=False,
                reason=type(error).__name__+':'+str(error),assertions=None,editable_assertions=None))
    return result


def project_eligibility(ranking,eligibility,budget):
    by_id={row['id']:row for row in eligibility}
    if len(by_id)!=len(eligibility) or len(ranking)!=len(by_id) or {row['id'] for row in ranking}!=set(by_id):
        raise ValueError('shared_eligibility_denominator_changed')
    eligible=[row for row in ranking if by_id[row['id']]['eligible']]
    return dict(eligible_count=len(eligible),selected_count=min(budget,len(eligible)),
        selected_ids=[row['id'] for row in eligible[:budget]],
        complete_ranking=[dict(id=row['id'],rank=i+1,raw_rank=row['rank']) for i,row in enumerate(eligible)],
        inventory_unknown_count=sum(row['status']=='unknown_inventory' for row in eligibility),
        eligibility='same frozen legacy singleton assertion interface in both arms')


def evidence_counts(ranking,selected_ids):
    """Source witness counts never describe expected-value or bug correctness."""
    selected=set(selected_ids)
    rows=[(row.get('evidence') or {},row['id'] in selected) for row in ranking]
    def key(reason):
        return reason.split(':',1)[0] if isinstance(reason,str) else reason.get('reason','unclassified_source_unknown')
    return dict(strong_candidates=sum(bool(e.get('strong_priority')) for e,_ in rows),
        may_candidates=sum(bool(e.get('may_priority')) for e,_ in rows),
        may_only_candidates=sum(bool(e.get('may_priority')) and not e.get('strong_priority') for e,_ in rows),
        strong_selected=sum(chosen and bool(e.get('strong_priority')) for e,chosen in rows),
        may_selected=sum(chosen and bool(e.get('may_priority')) for e,chosen in rows),
        may_only_selected=sum(chosen and bool(e.get('may_priority')) and not e.get('strong_priority') for e,chosen in rows),
        strong_witness_instances=sum(len(e.get('witnesses',[])) for e,_ in rows),
        may_witness_instances=sum(len(e.get('may_witnesses',[])) for e,_ in rows),
        unknown_reason_instances=dict(Counter(key(reason) for e,_ in rows
            for reason in [*e.get('unknowns',[]),*e.get('patch_unknowns',[])])))


def run(paired,output,budget=16):
    from experimental.patch_observation_priority import select as patch_select
    parent,ready=read(paired/'protocol.json'),read(paired/'ready.json')
    if digest(paired/'protocol.json')!=ready['protocol_sha256']:
        raise ValueError('paired_source_protocol_changed')
    inventory=Path(parent['inventory']);cases=parent['cases']
    if len(cases)!=17 or len(set(cases))!=17:
        raise ValueError('fixed_case_denominator_changed')
    inputs={str((paired/name).resolve()):digest(paired/name) for name in ('protocol.json','ready.json')}
    source_paths={}
    for case in cases:
        paths={name:inventory/case/name for name in ('case.json','corpus.json','frontend.json','source_pool.json')}
        for name,path in paths.items():
            if digest(path)!=parent['input_sha256'][case][name]:
                raise ValueError('fixed_inventory_source_changed')
            inputs[str(path.resolve())]=digest(path)
        case_record=read(paths['case.json']);patch=Path(case_record['candidate_patch'])
        patch_sha=digest(patch)
        if patch_sha!=case_record['repository_provenance']['patch_sha256'] or patch_sha!=next(
            row['sha256'] for row in case_record['artifacts'] if row['path']=='model.patch'):
            raise ValueError('submitted_patch_provenance_mismatch')
        inputs[str(patch.resolve())]=patch_sha;paths['patch']=patch;source_paths[case]=paths
    hashes={name:digest(ROOT/name) for name in FILES}
    output.mkdir(parents=True,exist_ok=False)
    write(output/'protocol.json',dict(version='patch-observation-priority-census-v1',
        source_inventory=str(inventory.resolve()),paired_protocol=str((paired/'protocol.json').resolve()),
        input_sha256=inputs,code_sha256=hashes,cases=cases,expected_candidates=4502,
        arms=ARM_MODES,budget_per_case=budget,
        primary='raw full-pool ranking exposure; all three arms select exactly the first 16 ranks',
        secondary='same frozen legacy singleton-eligible projection before taking 16 in all three arms',
        generation_inputs=['fixed source corpus','fixed source frontend','fixed source program candidates','submitted model.patch'],
        forbidden_inputs=['target labels','oracle responses','runtime outcomes','hidden verifier','reference patch','issue keywords'],
        provider_calls=0,subject_executions=0,
        evaluation='post-hoc only after input/code/eligibility/rank seal; no feedback to ranker',
        environment=dict(python=sys.version,packages={name:metadata.version(name) for name in
            ('tree-sitter','tree-sitter-go','tree-sitter-python','tree-sitter-typescript')})))
    for name in FILES:
        target=output/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    # Freeze every case's shared interface before any arm ranks any case.
    fixed_count=0
    for case,paths in source_paths.items():
        corpus,front,pool=[read(paths[name]) for name in ('corpus.json','frontend.json','source_pool.json')]
        candidates=fixed_programs(pool['candidates']);fixed_count+=len(candidates)
        write(output/case/'eligibility.json',source_eligibility(corpus,front,candidates))
    if fixed_count!=4502:raise ValueError('fixed_candidate_denominator_changed')
    write(output/'eligibility_seal.json',dict(candidates=fixed_count,
        files_sha256={str(path.relative_to(output)):digest(path) for path in sorted(output.glob('*/eligibility.json'))},
        algorithm_sha256={name:hashes[name] for name in ('experimental/singleton_oracle_slots.py',
            'experimental/assertion_operand_guard.py','scripts/census_patch_observation_priority.py')}))
    summaries={}
    for case,paths in source_paths.items():
        corpus,front,pool=[read(paths[name]) for name in ('corpus.json','frontend.json','source_pool.json')]
        candidates=fixed_programs(pool['candidates']);eligibility=read(output/case/'eligibility.json')
        stats={}
        for arm,mode in ARM_MODES.items():
            start=time.monotonic()
            result=(shape_select(corpus,candidates,budget=budget) if arm=='shape' else
                patch_select(corpus,front,candidates,paths['patch'].read_text(),budget=budget,mode=mode))
            elapsed=time.monotonic()-start
            raw_ids=validate_ranking(result,candidates,budget)
            write(output/case/(arm+'.json'),result)
            projection=project_eligibility(result['ranking'],eligibility,budget)
            write(output/case/(arm+'_eligible.json'),projection)
            eligible_by_id={row['id']:row for row in eligibility}
            stats[arm]=dict(input_count=len(candidates),raw_selected=len(raw_ids),
                raw_editable_selected=sum(eligible_by_id[cid]['eligible'] for cid in raw_ids),
                eligible_count=projection['eligible_count'],eligible_selected=projection['selected_count'],
                inventory_unknown_count=projection['inventory_unknown_count'],
                analysis_wall_seconds=round(elapsed,3),source_evidence=evidence_counts(result['ranking'],raw_ids))
            print(json.dumps(dict(case=case,arm=arm,**stats[arm])),flush=True)
        summaries[case]=stats
    write(output/'summary.json',dict(cases=summaries,candidate_count=fixed_count,
        interpretation='source exposure only; no new expected-value correctness or actual bug detection measured'))
    if hashes!={name:digest(ROOT/name) for name in FILES} or any(digest(path)!=sha for path,sha in inputs.items()):
        raise ValueError('source_or_algorithm_changed_during_census_no_seal')
    for name,sha in read(output/'eligibility_seal.json')['files_sha256'].items():
        if digest(output/name)!=sha:raise ValueError('shared_eligibility_changed_no_seal')
    write(output/'seal.json',dict(files_sha256={str(path.relative_to(output)):digest(path)
        for path in sorted(output.rglob('*')) if path.is_file()}))
    return dict(case_count=len(summaries),candidate_count=fixed_count,summary=str((output/'summary.json').resolve()))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--paired',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.paired,args.output,budget=16)))
