#!/usr/bin/env python3
"""Connect public archived inputs/observations to existing cluster members."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import posixpath
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from eviweave.behavior_clusters import candidate_materials
from eviweave.evidence import SourceGraph
from eviweave.material_entries import MaterialConnections
from eviweave.replay.trajectory import resolve_submission_actions
from eviweave.slice_behavior import write_behavior_graph
from pilot_port_admission import compressed
from pilot_material_representatives import read_views
from prepare_cluster_material_review import QUERIES
from verify_pre_slice_five_pilot import FR,original_sources


def public_documents(originals,actions):
    materials=[]
    for source,(path,raw) in originals.items():
        path=path if path.startswith('<') else posixpath.normpath(posixpath.join('/app',path))
        row={'source':source,'path':path,'text':raw.decode(),'kind':'file',
             'sha256':hashlib.sha256(raw).hexdigest()}
        if source.startswith(('H:','I:')):row['action_id']=source.split(':')[1]
        materials.append(row)
    for action in actions:
        materials.append({'source':'C:'+action['id'],'kind':'command','text':action['command'],
                          'action_id':action['id']})
        for field in ('output','output_head','output_tail'):
            if field in action['expected']:
                materials.append({'source':'O:'+action['id']+':'+field,'kind':'output',
                                  'text':action['expected'][field],'action_id':action['id'],'origin':'original'})
    return materials


def connect_views(originals,views,graphs,actions):
    documents=public_documents(originals,actions)
    connections=MaterialConnections(documents,actions,root='/app')
    by_view={}
    for identity,view in views.items():
        source=view['source']
        document=connections.documents[connections.ids[source]]
        owners=[document['action']] if 'action' in document else []
        by_view[identity]=connections.links([(graphs[source],view['ranges'])],actions=owners)
    used={row['material'] for links in by_view.values() for row in links}
    return {'documents':[connections.documents[m] for m in sorted(used)],
            'views':{str(v):links for v,links in by_view.items()}}


def run_case(job):
    case,clusters,out=job;sid=case['screen_id']
    actions,_=resolve_submission_actions(read_json(Path(case['input_directory'])/'trajectory.json'))
    originals=original_sources(case,actions=actions);views=read_views(sid)
    graphs={source:SourceGraph({'id':source,'path':originals[source][0],'raw':originals[source][1]})
            for source in {view['source'] for view in views.values()}}
    packet=connect_views(originals,views,graphs,actions)
    directory=out/'cases'/sid;directory.mkdir(parents=True)
    write_behavior_graph(directory/'candidate_materials.json.gz',packet)
    for name in ('memberships.json.gz','cluster_pairs.json.gz'):
        (directory/name).symlink_to(os.path.relpath(clusters/'cases'/sid/name,directory))
    members={int(c):rows for c,rows in compressed(directory/'memberships.json.gz')['ports'].items()}
    for rows in members.values():
        assert all(views[v]['source']==source for v,source,_ in rows)
    pairs=compressed(directory/'cluster_pairs.json.gz')['original']['ports']
    row={'case':sid,'task':case['task'],'views':len(views),'candidate_class_pairs':len(pairs),
         'linked_views':sum(bool(v) for v in packet['views'].values()),
         'documents':len(packet['documents']),
         'document_kinds':dict(Counter(d['kind'] for d in packet['documents'])),
         'relations':dict(Counter(link['relation'] for links in packet['views'].values() for link in links)),
         'shared_text_bytes':sum(len(d['text'].encode()) for d in packet['documents'] if d['text'] is not None),
         'artifact_bytes':(directory/'candidate_materials.json.gz').stat().st_size}
    write_json(directory/'metrics.json',row)
    print(sid,row['linked_views'],row['documents'],row['artifact_bytes'],flush=True)
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--clusters',type=Path,default=QUERIES)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--cases',nargs='+');p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();out=args.out.resolve();clusters=args.clusters.resolve()
    cases=read_json(FR/'cases.json')['cases']
    if args.cases:cases=[c for c in cases if c['screen_id'] in args.cases]
    write_json(out/'protocol.json',{'cases':[c['screen_id'] for c in cases],'clusters':str(clusters),
        'selection':'shared MaterialConnections over public code, commands and recorded observations; no manual labels',
        'context':'archived source/command provenance; static/package links are candidates, not invented syscall observations',
        'new_model_calls':0,'new_native_replays':0})
    (out/'adapter.py').write_bytes(Path(__file__).read_bytes())
    (out/'material_entries.py').write_bytes((ROOT/'src/eviweave/material_entries.py').read_bytes())
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows=list(pool.map(run_case,[(case,clusters,out) for case in cases]))
    write_json(out/'case_counts.json',rows)
    summary={'cases':len(rows),'candidate_class_pairs':sum(r['candidate_class_pairs'] for r in rows),
             **{key:sum(r[key] for r in rows) for key in ['views','linked_views','documents','shared_text_bytes','artifact_bytes']},
             'new_model_calls':0,'new_native_replays':0}
    write_json(out/'summary.json',summary);print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
