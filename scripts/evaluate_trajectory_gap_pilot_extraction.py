#!/usr/bin/env python3
"""Evaluation only: match frozen automatic gaps to separately authored manual labels.

This module is not imported by extraction or generation. It never executes tests.
It reports exact test identity and trajectory-step overlap separately.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def receipt(path):
    p=Path(path);return {'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}


def load_manual(paths):
    cases=[]
    for path in paths:
        data=json.loads(Path(path).read_text())
        for case in data['cases']:
            inp=case.get('generation_input',{})
            cases.append({'case':case['case'],'seed_ids':case.get('seed_ids',[s['test_id'] for s in inp.get('seeds',[])]),
                'step_ids':[str(x) for x in case.get('step_ids',inp.get('trajectory',{}).get('step_ids',[]))],
                'target_gap':case.get('target_gap',case.get('evaluation_only',{}).get('expected_gap')),
                'manual_source':receipt(path)})
    return cases


def compact(g):
    return {k:g[k] for k in ['id','rank','rule','strength','test_ids','step_ids']}


def evaluate(directory,manual_paths):
    directory=Path(directory);summary=json.loads((directory/'summary.json').read_text());rows=[]
    for label in load_manual(manual_paths):
        base=directory/label['case'];data=json.loads((base/'gaps.json').read_text());tests=json.loads((base/'tests.json').read_text());steps=json.loads((base/'steps.json').read_text())
        for field in ['tests','steps']:
            assert data['evidence_files'][field]==receipt(base/(field+'.json'))
        gs=data['gaps'];seeds=label['seed_ids'];wanted=set(label['step_ids'])
        for g in gs:
            assert all(t in tests for t in g['test_ids']) and all(s in steps for s in g['step_ids'])
        seed_rows=[]
        for tid in seeds:
            hits=[g for g in gs if tid in g['test_ids']]
            seed_rows.append({'test_id':tid,'present_in_inventory_only':tid in tests,'retrieved':bool(hits),
                'signal_count':len(hits),'best_rank':min((g['rank'] for g in hits),default=None),
                'best_rank_by_rule':{r:min(g['rank'] for g in hits if g['rule']==r) for r in sorted({g['rule'] for g in hits})},
                'signals':[compact(g) for g in hits]})
        step_rows=[]
        for step in label['step_ids']:
            hits=[g for g in gs if step in g['step_ids']]
            step_rows.append({'step_id':step,'retrieved':bool(hits),'signal_count':len(hits),
                'best_rank':min((g['rank'] for g in hits),default=None),'signals':[compact(g) for g in hits]})
        joint=[g for g in gs if set(seeds)&set(g['test_ids']) and wanted&set(g['step_ids'])]
        rows.append({**label,'inputs':{f:receipt(base/f) for f in ['gaps.json','tests.json','steps.json']},
            'gap_count':len(gs),'manual_seed_count':len(seeds),'retrieved_seed_count':sum(x['retrieved'] for x in seed_rows),
            'manual_step_count':len(wanted),'retrieved_step_count':sum(x['retrieved'] for x in step_rows),
            'seed_matches':seed_rows,'step_matches':step_rows,'joint_signal_count':len(joint),'joint_signals':[compact(g) for g in joint],
            'inventory_presence_is_not_retrieval':True,'step_overlap_is_not_mechanism_recovery':True})
    return {'version':'trajectory-gap-manual-mechanical-evaluation.v1','algorithm':receipt(__file__),'extraction_summary':receipt(directory/'summary.json'),
        'extractor_algorithm':summary['algorithm'],'manual_sources':[receipt(p) for p in manual_paths],
        'review_status':'Evaluation after labels became visible; root plus implementer review, not blind independent evaluation.',
        'definitions':{'exact_seed_hit':'Manual test_id occurs in an emitted gap.test_ids, not merely tests.json.',
            'step_hit':'Manual step_id occurs in an emitted gap.step_ids.',
            'joint_hit':'Same emitted gap links at least one exact seed and at least one manual step.',
            'semantic_same_origin':'Separate manually checked historical source match; never increases exact-ID numerator.',
            'mechanism_verdict':'Separate human full/partial/missed judgment. Identity overlap alone does not establish mechanism.'},
        'cases':rows,'totals':{'cases':len(rows),'seeds':sum(r['manual_seed_count'] for r in rows),'retrieved_seeds':sum(r['retrieved_seed_count'] for r in rows),
            'steps':sum(r['manual_step_count'] for r in rows),'retrieved_steps':sum(r['retrieved_step_count'] for r in rows),
            'cases_any_seed':sum(r['retrieved_seed_count']>0 for r in rows),'cases_all_seeds':sum(r['retrieved_seed_count']==r['manual_seed_count'] for r in rows),
            'cases_any_step':sum(r['retrieved_step_count']>0 for r in rows),'cases_joint':sum(r['joint_signal_count']>0 for r in rows)},
        'provider_calls':0,'target_executions':0,'extraction_modified':False}


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--extraction',type=Path,required=True);p.add_argument('--manual',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=evaluate(a.extraction,a.manual);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result['totals']))

if __name__=='__main__':main()
