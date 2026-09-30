"""Post-seal evaluator-only matching of historical program materials.

The fixed historical matcher is never supplied to the scheduler. This reads
already audited candidate IDs, not hidden tests, reference patches or expected
oracle source. Exposure does not prove correctness or defect detection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def evaluate(schedule,historical_matching,output):
    # Verify frozen label-free scheduling before opening the evaluator matcher.
    protocol=read(schedule/'protocol.json')
    for name,expected in read(schedule/'seal.json')['files_sha256'].items():
        if digest(schedule/name)!=expected:raise ValueError('Label-free schedule changed before evaluation')
    truth=read(historical_matching)
    matching={r['case']:r for r in truth['cases']}
    if set(matching)!=set(protocol['cases']):raise ValueError('Historical matching task denominator differs')
    rows=[]
    for case in protocol['cases']:
        result=read(schedule/case/'schedule.json')
        reference=matching[case]
        target=set(reference['matching_ids'])
        all_ids={cid for g in result['arms']['sha_first4']['groups'] for cid in g['member_ids']}
        # The first-four cap intentionally leaves family members unshown; use
        # the original complete rank catalogue to establish available IDs.
        rank_path=Path(protocol['impact'])/case/'ranking.json'
        available={r['id'] for r in read(rank_path)['impact']['ranking']}
        if not target<=available:raise ValueError('Historical IDs differ from the fixed source cohort')
        candidate_to_family={}
        catalogue=read(Path(protocol['census'])/case/'catalogue.json')
        for family in catalogue['families']:
            for variant in family['variants']:candidate_to_family[variant['candidate_id']]=family['id']
        target_families={candidate_to_family[cid] for cid in target}
        row=dict(case=case,requires_semantic_revision=reference['requires_semantic_revision'],
            historical_material_in_pool=bool(target),matching_material_count=len(target),
            original_singleton_exposed=bool(target&set(result['original_eligible_singleton_prefix'])),arms={})
        for policy,arm in result['arms'].items():
            selected_families=set(arm['selected_family_ids'])
            selected_members=set(arm['selected_member_ids'])
            row['arms'][policy]=dict(groups=arm['selected_group_count'],members=arm['selected_member_count'],
                historical_family_exposed=bool(target_families&selected_families),
                historical_member_exposed=bool(target&selected_members),
                selected_family_but_member_cap_excluded_target=bool(target_families&selected_families) and not bool(target&selected_members))
        rows.append(row)
    semantic=[r for r in rows if r['requires_semantic_revision']]
    if len(rows)!=17 or len(semantic)!=5:raise ValueError('The fixed historical denominators must be seventeen/five')
    summary={}
    for name,subset in [('all17',rows),('semantic5',semantic)]:
        summary[name]=dict(denominator=len(subset),historical_material_in_pool=sum(r['historical_material_in_pool'] for r in subset),
            original_singleton_exposed=sum(r['original_singleton_exposed'] for r in subset),
            arms={policy:dict(historical_families_exposed=sum(r['arms'][policy]['historical_family_exposed'] for r in subset),
                             historical_members_exposed=sum(r['arms'][policy]['historical_member_exposed'] for r in subset),
                             member_cap_exclusions=sum(r['arms'][policy]['selected_family_but_member_cap_excluded_target'] for r in subset))
                  for policy in ['sha_first4','impact_first4']})
    output.mkdir(parents=True,exist_ok=False)
    review=dict(role='evaluator_only_never_generator_or_provider_input',schedule_protocol_sha256=digest(schedule/'protocol.json'),
        schedule_seal_sha256=digest(schedule/'seal.json'),historical_matching_sha256=digest(historical_matching),
        evaluator_script_sha256=digest(Path(__file__)),historical_matching=str(historical_matching.resolve()),
        matching='Existing independently audited historical program-material candidate IDs; fixed before this scheduler.',
        summary=summary,cases=rows,provider_calls=0,subject_executions=0,
        limits=['Historical exact program-material coverage only; alternative equivalent witnesses are not enumerated.',
                'A target family can be shown while its target member is excluded by the fixed cap.',
                '272 groups expose 471 members, compared with 272 singleton members; no equal-cost or equal-token superiority claim.',
                'No complete-oracle correctness, native failure or actual target detection has been established.',
                'Old v3 16/17 score remains unchanged.'])
    write(output/'review.json',review)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--schedule',type=Path,required=True)
    parser.add_argument('--historical-matching',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(evaluate(args.schedule,args.historical_matching,args.output)))
