#!/usr/bin/env python3
"""Projected F-view pair domains; source-wide neighborhoods are not donors."""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from pilot_port_relations import prepare_case,write_gzip,OLD,FR


def count_pairs(groups,domains):
    masks=[sum(1<<view for view in {row[0] for row in g['members']}) for g in groups]
    pair_masks=defaultdict(int)
    for domain in domains:
        family=domain['groups'];suffix=[0]*(len(family)+1)
        for at in range(len(family)-1,-1,-1):suffix[at]=suffix[at+1]|masks[family[at]]
        prefix=0
        for at,g in enumerate(family):
            for view in {r[0] for r in groups[g]['anchors']}:
                pair_masks[view]|=(prefix|suffix[at+1]) & ~(1<<view)
            prefix|=masks[g]
    return sum(mask.bit_count() for mask in pair_masks.values())


def run_case(job):
    case,out=job;sid=case['screen_id'];started=time.perf_counter()
    index,records,_,anchors,unmatched,anchor_views=prepare_case(case)
    inverse=defaultdict(set)
    for key,views in anchor_views.items():
        for view in views:inverse[view].add(key)
    views=[]
    for source,record in records.items():
        for number,view in enumerate(record['views']):
            nodes={n for f in view['files'] if f['material']==source for n in f['nodes']+f['context_nodes']}
            views.append({'id':len(views),'source':source,'original_view':number,'nodes':nodes,
                          'anchors':inverse[source,number]})
    groups,domains=index.grouped_view_domains(views)
    result={'case':sid,'task':case['task'],'language':case['language'],'source_versions':len(records),
        'slice_views':len(views),'unique_operation_anchors':len(anchors),
        'nonoperation_anchor_positions':len(unmatched),
        'operation_view_occurrences':sum(len(g['members']) for g in groups),
        'anchor_view_occurrences':sum(len(g['anchors']) for g in groups),
        'same_operation_occurrence_pairs':sum(d['occurrence_pairs'] for d in domains),
        'changed_relation_occurrence_pairs':sum(d['changed_occurrence_pairs'] for d in domains),
        'directed_candidate_slice_pairs':count_pairs(groups,domains),
        'all_directed_slice_pairs':len(views)*(len(views)-1),'profile_groups':len(groups),
        'seconds':time.perf_counter()-started}
    directory=out/'cases'/sid
    write_gzip(directory/'slices.json.gz',records)
    write_gzip(directory/'domains.json.gz',{'views':[{'id':v['id'],'source':v['source'],'original_view':v['original_view']} for v in views],
                                          'groups':groups,'domains':domains})
    write_json(directory/'metrics.json',result)
    print(sid,result['directed_candidate_slice_pairs'],round(result['seconds'],1),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--cases',nargs='+')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True)
    cases=read_json(FR/'cases.json')['cases']
    if args.cases:cases=[c for c in cases if c['screen_id'] in args.cases]
    write_json(out/'protocol.json',{'case_ids':[c['screen_id'] for c in cases],'input':str(OLD),
        'neighborhood':'Recompute current F from frozen D byte coordinates; never reuse old AST node IDs. Neighbor operations must be in this F view. Port-reachable definition chains retain their original source coordinates.',
        'pairs':'Directed distinct-view pairs with a named/unknown operation candidate and a different projected relation signature. Not validated executable plans.',
        'missing_channels':['arbitrary cross-API interface pairs','material-only pairs','new-operation synthesis'],
        'model_calls':0,'labels_in_algorithm':False})
    code=out/'code';code.mkdir()
    for path in ['scripts/pilot_view_port_relations.py','scripts/pilot_port_relations.py','src/eviweave/relational_alignment.py']:
        (code/Path(path).name).write_bytes((ROOT/path).read_bytes())
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(run_case,[(c,out) for c in cases]))
    write_json(out/'counts.json',rows)
    fields=['source_versions','slice_views','unique_operation_anchors','operation_view_occurrences','anchor_view_occurrences',
            'same_operation_occurrence_pairs','changed_relation_occurrence_pairs','directed_candidate_slice_pairs','all_directed_slice_pairs','profile_groups']
    write_json(out/'summary.json',{'trajectories':len(rows),'distinct_tasks':len({r['task'] for r in rows}),
                                  **{key:sum(r[key] for r in rows) for key in fields}})


if __name__=='__main__':main()
