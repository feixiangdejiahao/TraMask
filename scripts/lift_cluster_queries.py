#!/usr/bin/env python3
"""Preserve the original query domain and add entry-connected providers."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from eviweave.behavior_clusters import cluster_queries
from pilot_behavior_deltas import load_case
from verify_pre_slice_five_pilot import FR

MODES=['ports','relations']


def compressed(path):
    with gzip.open(path,'rt') as f:return json.load(f)


def run_case(job):
    case,source_run,out=job;sid=case['screen_id'];index,records,_=load_case(case)
    memberships=compressed(source_run/'cases'/sid/'memberships.json.gz')
    previous=compressed(source_run/'cases'/sid/'cluster_pairs.json.gz')
    row=read_json(source_run/'cases'/sid/'metrics.json');final={}
    for mode in MODES:
        groups=memberships[mode]
        assignments={tuple(member):int(cid) for cid,members in groups.items() for member in members}
        original=set(map(tuple,previous['original'][mode]))
        edges=cluster_queries(index,records,assignments)|original
        assert original<=edges
        final[mode]=sorted(edges)
        row['arms'][mode]['before_seed_lifting']=len(original)
        row['arms'][mode]['full_domain_cluster_pairs']=len(edges)
    directory=out/'cases'/sid
    write_json(directory/'metrics.json',row)
    for filename in ['memberships.json.gz','candidate_materials.json.gz']:
        (directory/filename).symlink_to(os.path.relpath(source_run/'cases'/sid/filename,directory))
    with gzip.open(directory/'cluster_pairs.json.gz','wt') as f:json.dump({'original':final},f,separators=(',',':'))
    print(sid,{m:len(xs) for m,xs in final.items()},flush=True);return row


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();out=args.out.resolve();source_run=args.input.resolve();out.mkdir(parents=True)
    write_json(out/'protocol.json',{'source':str(source_run),'step':'Query activation over existing weak data dependencies; no extra slicing, no discarded original pairs. Candidate material links are retained.',
        'new_model_calls':0,'new_native_executions':0})
    selected=set(read_json(source_run/'protocol.json')['cases'])
    cases=[c for c in read_json(FR/'cases.json')['cases'] if c['screen_id'] in selected]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(run_case,[(c,source_run,out) for c in cases]))
    write_json(out/'counts.json',rows)
    summary=read_json(source_run/'summary.json')
    summary['arms']={m:summary['arms'][m] for m in MODES}
    for mode in summary['arms']:
        summary['arms'][mode]['before_seed_lifting']=sum(r['arms'][mode]['before_seed_lifting'] for r in rows)
        summary['arms'][mode]['full_domain_cluster_pairs']=sum(r['arms'][mode]['full_domain_cluster_pairs'] for r in rows)
    write_json(out/'summary.json',summary)
    (out/'lifter.py').write_bytes(Path(__file__).read_bytes())
    (out/'behavior_clusters.py').write_bytes((ROOT/'src/eviweave/behavior_clusters.py').read_bytes())


if __name__=='__main__':main()
