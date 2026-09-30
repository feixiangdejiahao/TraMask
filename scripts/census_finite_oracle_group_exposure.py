"""Label-free group exposure using already frozen original impact rankings.

Do not import the generator/provider or open evaluator targets. Target matching
is a separate post-seal phase and cannot alter this schedule.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from collections import Counter


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text())
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
def sha(value): return hashlib.sha256(value.encode()).hexdigest()


def schedule(catalogue,ranking,budget=16,maximum_members=4):
    records=ranking['impact']['ranking']
    ids=[r['id'] for r in records]
    expected_ids=list(catalogue['candidate_info'])
    if len(set(ids))!=len(ids) or set(ids)!=set(expected_ids):
        raise ValueError('Frozen impact ranking/catalogue candidate identity mismatch')
    if [row['rank'] for row in records]!=list(range(1,len(records)+1)):
        raise ValueError('Frozen impact rank ordering is incomplete')
    positions={row['id']:row['rank'] for row in records}
    families={f['id']:f for f in catalogue['families']}
    ordered=[];seen=set()
    for row in records:
        family_id=catalogue['candidate_info'][row['id']]['family_id']
        if family_id not in seen:
            seen.add(family_id);ordered.append((family_id,row['id'],row['rank']))
    arms={}
    for policy in ['sha_first4','impact_first4']:
        groups=[]
        for index,(family_id,first_id,first_rank) in enumerate(ordered):
            family=families[family_id]
            variants=family['variants']
            key=(lambda v:(sha(v['candidate_id']),v['candidate_id'])) if policy=='sha_first4' else (
                 lambda v:(positions[v['candidate_id']],v['candidate_id']))
            selected=sorted(variants,key=key)[:maximum_members]
            groups.append(dict(group_rank=index+1,family_id=family_id,first_impact_candidate=first_id,
                first_impact_rank=first_rank,family_size=len(variants),
                selected=index<budget,member_ids=[v['candidate_id'] for v in selected],
                source_structurally_offerable=family['status']=='factorized' and all(
                    any(a['editable'] for a in v['assertions']) for v in selected),
                family_factorization_status=family['status'],
                highest_impact_member_retained=first_id in {v['candidate_id'] for v in selected}))
        prefix=groups[:budget]
        members=[cid for group in prefix for cid in group['member_ids']]
        if len(members)!=len(set(members)): raise ValueError('A selected member appears twice')
        arms[policy]=dict(groups=groups,selected_group_count=len(prefix),selected_member_count=len(members),
            selected_member_ids=members,unofferable_selected_groups=sum(not g['source_structurally_offerable'] for g in prefix),
            selected_family_ids=[g['family_id'] for g in prefix],
            dropped_highest_impact_members=sum(not g['highest_impact_member_retained'] for g in prefix))
    singles=[row['id'] for row in records if row['evidence']['eligible']][:budget]
    return dict(input_candidates=len(ids),families=len(ordered),budget_groups=budget,maximum_members_per_group=maximum_members,
        arms=arms,original_eligible_singleton_prefix=singles,original_singleton_member_count=len(singles),
        original_singleton_budget=budget,cost_comparability='16 groups can offer more than 16 candidates. This census measures exposure only, not equal token/call cost, correct oracle or target detection.')


def run(census,impact,inventory,output):
    output.mkdir(parents=True,exist_ok=False)
    census_protocol=read(census/'protocol.json')
    cases=census_protocol['cases']
    for record in read(impact/'protocol.json')['code']:
        if digest(Path(record['path']))!=record['sha256']:
            raise ValueError('Frozen original impact code snapshot changed')
    for name,expected in read(census/'seal.json')['files_sha256'].items():
        if digest(census/name)!=expected: raise ValueError('Sealed template census changed: '+name)
    paths={case:dict(catalogue=census/case/'catalogue.json',ranking=impact/case/'ranking.json',
                     source_pool=inventory/case/'source_pool.json') for case in cases}
    hashes={case:{name:digest(path) for name,path in values.items()} for case,values in paths.items()}
    write(output/'protocol.json',dict(version='finite-family-impact-exposure-v1',cases=cases,expected_candidates=4502,
        census=str(census.resolve()),impact=str(impact.resolve()),inventory=str(inventory.resolve()),
        input_sha256=hashes,script_sha256=digest(Path(__file__)),
        ranking='Frozen impact_rank_v1 original production local-dependence ranking; not the modified-source graph arm.',
        family_order='First appearance of each stable family ID in the original complete impact ranking; never skip unofferable families.',
        member_policies=['SHA256(candidate.id) first four','Original impact rank first four (fixed diagnostic arm)'],
        group_budget=16,maximum_members_per_group=4,selection_inputs='Only sealed source catalogue and frozen original ranking.',
        target_labels_opened=False,provider_calls=0,subject_executions=0,
        cost_claim='No equal-budget claim against sixteen singleton candidates; no oracle/goal claim from exposure.'))
    summaries={}
    for case in cases:
        catalogue,ranking=read(paths[case]['catalogue']),read(paths[case]['ranking'])
        for source in ranking['source_files']:
            if digest(Path(source['path']))!=source['sha256']: raise ValueError('Frozen rank source changed: '+case)
            name=Path(source['path']).name
            if source['sha256']!=census_protocol['input_sha256'][case][name]['sha256']:
                raise ValueError('Frozen rank source differs from template cohort: '+case+'/'+name)
        if Counter(c['id'] for c in read(paths[case]['source_pool'])['candidates'])!=Counter(catalogue['candidate_info'].keys()):
            raise ValueError('Candidate pool and family catalogue differ: '+case)
        result=schedule(catalogue,ranking)
        write(output/case/'schedule.json',result)
        summary={key:result[key] for key in ['input_candidates','families','original_singleton_member_count']}
        summary['arms']={policy:{key:value for key,value in arm.items() if key not in ['groups','selected_member_ids','selected_family_ids']} for policy,arm in result['arms'].items()}
        summaries[case]=summary
        print(json.dumps(dict(case=case,**summary)),flush=True)
    if any(digest(path)!=hashes[case][name] for case,values in paths.items() for name,path in values.items()):
        raise ValueError('Inputs changed while scheduling; no seal')
    if sum(row['input_candidates'] for row in summaries.values())!=4502: raise ValueError('Cohort candidate denominator changed')
    write(output/'summary.json',summaries)
    write(output/'seal.json',dict(files_sha256={str(path.relative_to(output)):digest(path) for path in sorted(output.rglob('*')) if path.is_file()}))
    return dict(cases=len(cases),candidates=4502,selected_members_by_arm={policy:sum(row['arms'][policy]['selected_member_count'] for row in summaries.values()) for policy in ['sha_first4','impact_first4']},
                selected_groups_by_arm={policy:sum(row['arms'][policy]['selected_group_count'] for row in summaries.values()) for policy in ['sha_first4','impact_first4']},provider_calls=0,subject_executions=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--census',type=Path,required=True)
    parser.add_argument('--impact',type=Path,required=True)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.census,args.impact,args.inventory,args.output)))
