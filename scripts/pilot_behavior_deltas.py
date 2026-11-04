#!/usr/bin/env python3
"""Freeze admission, then measure role-local difference and binding domains."""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from eviweave.artifacts import read_json, write_json
from eviweave.behavior import BehaviorIndex
from eviweave.behavior_deltas import BehaviorDeltaIndex
from comparison_audit import difference_domains
from eviweave.evidence import SourceGraph
from eviweave.comparison import index_views
from eviweave.port_admission import admission_witnesses
from pilot_port_admission import FROZEN, compressed, endpoint_operations
from verify_pre_slice_five_pilot import FR, original_sources

ADMISSION = ROOT/'results/behavioral_masking/20261105_port_admission_n88_r07'


def load_case(case,*,originals=None):
    frozen = FROZEN/'cases'/case['screen_id']
    data = compressed(frozen/'domains.json.gz'); slices = compressed(frozen/'slices.json.gz')
    if originals is None:originals = original_sources(case)
    sources = {}
    for source, record in slices.items():
        path, raw = originals[source]
        assert hashlib.sha256(raw).hexdigest() == record['sha256']
        graph = SourceGraph({'id':source,'path':path,'raw':raw})
        sources[source] = graph, BehaviorIndex(graph)
    anchors = defaultdict(set)
    for group in data['groups']:
        for v, op in group['anchors']:
            anchors[v].add((data['views'][v]['source'], op))
    bodies, views = {}, {}
    for v in data['views']:
        record = slices[v['source']]['views'][v['original_view']]
        body = json.dumps({k:x for k,x in record.items() if k != 'entries'}, sort_keys=True)
        identity = bodies.setdefault(body, len(bodies))
        if identity not in views:
            views[identity] = {'id':identity,'source':v['source'],
                'nodes':{n for f in record['files'] for n in f['nodes']+f['context_nodes']},'anchors':set(),
                'ranges':[span for f in record['files'] for span in f['ranges']]}
        views[identity]['anchors'].update(anchors[v['id']])
    index, records = index_views(sources,list(views.values()))
    return index, records, list(views.values())


def run_case(job):
    case, out = job; sid = case['screen_id']; started = time.perf_counter()
    index, records, _ = load_case(case)
    result=difference_domains(index,records)
    raw_masks=result['view_pairs'];examples=result['examples']
    deltas=BehaviorDeltaIndex(index)
    by_key=defaultdict(list)
    for record in records:by_key[record['key']].append(record)
    frozen = {int(v):int(m,16) for v,m in read_json(ADMISSION/'cases'/sid/'pair_masks.json')['two_edge'].items() if int(m,16)}
    actual = {v:m for v,m in raw_masks.items() if m}
    assert actual == frozen, sid
    row = {'case':sid,'task':case['task'],'language':case['language'],
        'fixed_admitted_slice_pairs':sum(m.bit_count() for m in frozen.values()),**result['metrics'],
        'all_admitted_slice_pairs_preserved':True,'seconds':time.perf_counter()-started}
    # Manual data enter only after the entire algorithm output is frozen.
    directory = out/'cases'/sid
    write_json(directory/'metrics.json',row); write_json(directory/'examples.json',examples)
    evaluation = []
    for item in read_json(ROOT/'research/behavior_alignment_pilot_20261104/alignment_expectations.json')['expectations']:
        if item['case'] != sid or item['right'] is None:
            continue
        keys = [endpoint_operations(index,item[side]['source'],item[side]['start'],item[side]['end'])
                for side in ['left','right']]
        candidates = [(a,b) for ak in keys[0] for bk in keys[1] for a in by_key[ak] for b in by_key[bk]
                      if a['interface'] == b['interface'] and
                      admission_witnesses(a,'two_edge') & admission_witnesses(b,'two_edge')]
        comparisons = []
        seen = {}
        for a,b in candidates:
            key = a['key'], b['key'], tuple(sorted(a['roles'],key=repr)), tuple(sorted(b['roles'],key=repr))
            admitted = (a['anchor'] and a['view'] != b['view'] and
                        (a['exact'] != b['exact'] or admission_witnesses(a,'two_edge') != admission_witnesses(b,'two_edge')))
            if key in seen:
                comparisons[seen[key]]['inside_fixed_operation_domain'] |= admitted
                continue
            seen[key] = len(comparisons)
            comparisons.append({'left':a['key'],'right':b['key'],**deltas.difference(a,b),
                'inside_fixed_operation_domain':admitted,
                'source_edits':deltas.syntax_difference(a['key'],b['key'])})
        evaluation.append({'id':item['id'],'status':item['expected']['status'],
            'relation':item['expected']['relation'],'comparisons':comparisons[:10],
            'comparison_count':len(comparisons)})
    write_json(directory/'endpoint_evaluation.json',evaluation)
    print(sid,row['old_operation_profile_pairs'],row['concrete_local_difference_domains'],row['parameterised_difference_domains'],round(row['seconds'],1),flush=True)
    return row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cases',nargs='+');parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True)
    cases=read_json(FR/'cases.json')['cases']
    if args.cases:
        cases=[c for c in cases if c['screen_id'] in args.cases]
    write_json(out/'protocol.json',{'cases':[c['screen_id'] for c in cases],
        'fixed_admission':str(ADMISSION),'mode':'two_edge','algorithm_inputs':'public sources, current F graph, D anchors',
        'new_filter':False,'concrete_domains':'Keep every admitted view/operation and all payload bindings; count shared plans, not deletion of concrete alternatives.',
        'manual_data':'Read after each case metrics and examples are frozen, for endpoint evaluation only.',
        'new_model_calls':0})
    (out/'code').mkdir()
    for file in ['scripts/pilot_behavior_deltas.py','src/eviweave/behavior_deltas.py']:
        (out/'code'/Path(file).name).write_bytes((ROOT/file).read_bytes())
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(run_case,[(c,out) for c in cases]))
    write_json(out/'counts.json',rows)
    names=['fixed_admitted_slice_pairs','old_operation_profile_pairs','concrete_local_difference_domains',
           'parameterised_difference_domains','unchanged_local_relation_pairs_retained_as_residual','parameter_only_pairs']
    summary={'cases':len(rows),'tasks':len({r['task'] for r in rows}),**{k:sum(r[k] for r in rows) for k in names}}
    write_json(out/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
