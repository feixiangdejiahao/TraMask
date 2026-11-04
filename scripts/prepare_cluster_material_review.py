#!/usr/bin/env python3
"""Locate evaluation references in actual retained candidate-view payloads."""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from eviweave.pre_slice import covered
from pilot_port_admission import FROZEN,compressed
from verify_pre_slice_five_pilot import FR,original_sources

QUERIES=ROOT/'results/behavioral_masking/20261105_behavior_cluster_queries_n88_r02'


def load_views(case):
    sid=case['screen_id'];sources=original_sources(case)
    slices=compressed(FROZEN/'cases'/sid/'slices.json.gz')
    domains=compressed(FROZEN/'cases'/sid/'domains.json.gz')
    bodies={};views={}
    for v in domains['views']:
        row=slices[v['source']]['views'][v['original_view']]
        body=json.dumps({k:x for k,x in row.items() if k!='entries'},sort_keys=True)
        identity=bodies.setdefault(body,len(bodies))
        views[identity]={'id':identity,'source':v['source'],'path':sources[v['source']][0],
            'ranges':[r for f in row['files'] for r in f['ranges']]}
    memberships=compressed(QUERIES/'cases'/sid/'memberships.json.gz')['ports']
    for v in views.values():v['clusters']=[]
    for cluster,members in memberships.items():
        for v,source,operation in members:
            assert views[v]['source']==source
            views[v]['clusters'].append(int(cluster))
    for v in views.values():v['clusters']=sorted(set(v['clusters']))
    return sources,views


def prepare(job):
    case,out=job;sid=case['screen_id'];sources,views=load_views(case)
    doc=read_json(FR/'observation/adjudicated'/f'{sid}.json')
    by_source=defaultdict(list)
    for view in views.values():by_source[view['source']].append(view)
    references=[]
    for factor in doc['missing_factors']:
        for n,fragment in enumerate(factor['source_fragments']):
            code=fragment['code'] if 'code' in fragment else fragment['literal_fragment']
            literal=code.strip().encode();pattern=re.compile(rb'\s+'.join(re.escape(x) for x in re.split(rb'\s+',literal)))
            hits=[]
            for source,ss in by_source.items():
                raw=sources[source][1]
                for match in pattern.finditer(raw):
                    a,b=match.span()
                    available=[v['id'] for v in ss if covered(a,b,v['ranges'])]
                    if available:hits.append({'source':source,'range':[a,b],'views':available,'text':raw[a:b].decode()})
            references.append({'factor':factor['factor_id'],'reference':n,'code':code,'hits':hits})
    directory=out/'cases'/sid
    write_json(directory/'views.json',list(views.values()));write_json(directory/'reference_locations.json',references)
    # The manual reviewer reads these requirements, then inspects real payloads
    # and eligible candidate edges; a quote hit alone is not a positive verdict.
    write_json(directory/'requirements.json',{k:doc[k] for k in ['target_operation','required_factor_inventory','missing_factors','oracle_availability','minimal_assembly']})
    write_json(directory/'base_units.json',doc['agent_base_units'])
    print(sid,len(views),[(r['factor'],len(r['hits'])) for r in references],flush=True)


def show_view(case,identity):
    sources,views=load_views(case);v=views[identity];raw=sources[v['source']][1]
    lines=[f"VIEW {identity}; {v['source']}; {v['path']}; clusters={v['clusters']}"]
    for a,b in v['ranges']:
        first=raw[:a].count(b'\n')+1
        lines.append(f'--- bytes {a}:{b}; first line {first} ---\n'+raw[a:b].decode())
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--view',nargs=2,metavar=('CASE','VIEW'));p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();out=args.out.resolve();protocol=read_json(out/'protocol.json')
    if args.view:
        sid,identity=args.view;case=next(c for c in protocol['cases'] if c['screen_id']==sid)
        text=show_view(case,int(identity));path=out/'cases'/sid/'inspected_views'/f'{identity}.txt'
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);print(text)
        return
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(prepare,[(case,out) for case in protocol['cases']]))
    (out/'preparer.py').write_bytes(Path(__file__).read_bytes())


if __name__=='__main__':main()
