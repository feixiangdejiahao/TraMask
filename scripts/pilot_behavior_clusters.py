#!/usr/bin/env python3
"""Compare rooted partitions on exactly the previous admitted pair domain."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from eviweave.behavior_clusters import observed_fields
from comparison_audit import partition_records
from eviweave.replay.trajectory import resolve_submission_actions
from eviweave.slice_behavior import write_behavior_graph
from attach_cluster_materials import connect_views
from pilot_behavior_deltas import load_case,ADMISSION
from verify_pre_slice_five_pilot import FR,original_sources

MODES=['ports','relations','flow','boundary']


def run_case(job):
    case,out=job;sid=case['screen_id'];started=time.perf_counter()
    actions,_=resolve_submission_actions(read_json(Path(case['input_directory'])/'trajectory.json'))
    originals=original_sources(case,actions=actions)
    index,records,views=load_case(case,originals=originals)
    fields=observed_fields((FR/'public_inputs'/sid/'patch.diff').read_text())
    result=partition_records(index,records,views,fields,modes=MODES)
    frozen={int(v):int(m,16) for v,m in read_json(ADMISSION/'cases'/sid/'pair_masks.json')['two_edge'].items() if int(m,16)}
    expected={int(v):int(m,16) for v,m in read_json(ADMISSION/'cases'/sid/'pair_masks.json')['old'].items() if int(m,16)}
    assert {v:m for v,m in result['admitted_view_pairs'].items() if m}==frozen,sid
    assert {v:m for v,m in result['original_view_pairs'].items() if m}==expected,sid
    row={'case':sid,'task':case['task'],'language':case['language'],**result['metrics'],
         'original_occurrences_preserved':True,'seconds':time.perf_counter()-started}
    directory=out/'cases'/sid;write_json(directory/'metrics.json',row)
    write_behavior_graph(directory/'memberships.json.gz',{
        mode:{str(identity):sorted(rows) for identity,rows in groups.items()}
        for mode,groups in result['memberships'].items()})
    write_behavior_graph(directory/'cluster_pairs.json.gz',{
        kind:{mode:sorted(rows) for mode,rows in groups.items()}
        for kind,groups in result['cluster_pairs'].items() if kind!='lifted'})
    packet=connect_views(originals,{v['id']:v for v in views},
                         {source:g for source,(g,_) in index.sources.items()},actions)
    write_behavior_graph(directory/'candidate_materials.json.gz',packet)
    print(sid,row['old_profile_pairs'],{m:row['arms'][m]['cluster_pairs'] for m in MODES},round(row['seconds'],1),flush=True)
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--cases',nargs='+');p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True)
    cases=read_json(FR/'cases.json')['cases']
    if args.cases:cases=[c for c in cases if c['screen_id'] in args.cases]
    write_json(out/'protocol.json',{'cases':[c['screen_id'] for c in cases],'fixed_admission':str(ADMISSION),
        'algorithm_inputs':'public sources, current F, D anchors; no human annotations, reference code or test outcomes',
        'modes':MODES,'claim':'cluster pairs are planning queries, concrete alternatives remain; no semantic-equivalence certificate',
        'new_model_calls':0,'new_native_executions':0})
    (out/'code').mkdir()
    for path in ['scripts/pilot_behavior_clusters.py','src/eviweave/behavior_clusters.py']:
        (out/'code'/Path(path).name).write_bytes((ROOT/path).read_bytes())
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(run_case,[(c,out) for c in cases]))
    write_json(out/'counts.json',rows)
    summary={'cases':len(rows),'tasks':len({r['task'] for r in rows}),
        'fixed_slice_pairs':sum(r['fixed_slice_pairs'] for r in rows),'old_profile_pairs':sum(r['old_profile_pairs'] for r in rows),
        'original_slice_pairs':sum(r['original_slice_pairs'] for r in rows),
        'arms':{m:{key:sum(r['arms'][m][key] for r in rows) for key in rows[0]['arms'][m]} for m in MODES}}
    write_json(out/'summary.json',summary);print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
