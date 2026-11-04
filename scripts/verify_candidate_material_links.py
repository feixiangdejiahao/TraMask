#!/usr/bin/env python3
"""Verify exported candidate documents against public bytes, then check known omissions."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from eviweave.artifacts import read_json,write_json
from eviweave.behavior_clusters import read_candidate_materials
from eviweave.replay.trajectory import resolve_submission_actions
from eviweave.slice_behavior import read_behavior_graph
from verify_pre_slice_five_pilot import FR,original_sources

OLD=ROOT/'results/behavioral_masking/20261105_cluster_material_review_n16_r01'


def verify_case(job):
    case,run,previous=job;sid=case['screen_id'];directory=run/'cases'/sid
    actions,_=resolve_submission_actions(read_json(Path(case['input_directory'])/'trajectory.json'))
    originals=original_sources(case,actions=actions);by_action={a['id']:a for a in actions}
    bundle=read_behavior_graph(directory/'candidate_materials.json.gz')
    docs={d['id']:d for d in bundle['documents']}
    for doc in docs.values():
        source=doc['source']
        if doc['kind']=='file':assert doc['text'].encode()==originals[source][1]
        elif doc['kind']=='command':assert doc['text']==by_action[doc['action']]['command']
        else:
            _,action,field=source.split(':');assert doc['origin']=='original'
            assert doc['text']==by_action[action]['expected'][field]
    members=read_behavior_graph(directory/'memberships.json.gz')['ports']
    before_members=read_behavior_graph(previous/'cases'/sid/'memberships.json.gz')['ports']
    pairs=read_behavior_graph(directory/'cluster_pairs.json.gz')['original']['ports']
    assert members==before_members
    assert pairs==read_behavior_graph(previous/'cases'/sid/'cluster_pairs.json.gz')['original']['ports']
    views={v for rows in members.values() for v,_,_ in rows}
    assert all(str(v) in bundle['views'] for v in views)
    for links in bundle['views'].values():
        assert all(link['material'] in docs for link in links)
    result={'case':sid,'documents_byte_equal':len(docs),'candidate_pairs':len(pairs),
            'members_unchanged':True,'pairs_unchanged':True,'member_views':len(views),
            'linked_member_views':sum(bool(bundle['views'][str(v)]) for v in views)}
    write_json(directory/'verification.json',result)
    return result


def targeted(run):
    expected=read_json(OLD/'excluded_materials.json');rows=[]
    for sid in ['S010','S057','S015']:
        old=read_json(OLD/'cases'/sid/'manual_review.json')
        packet=read_candidate_materials(run/'cases'/sid,old['candidate'],member_views=old['views'])
        checks=[]
        for item in expected:
            if item['case']!=sid:continue
            source='O:s54_c0:output' if sid=='S015' else item['source']
            docs=[d for d in packet['candidate_materials'] if d['source']==source and item['text'] in d['text']]
            assert docs, (sid,source)
            checks.append({'source':source,'materials':[d['id'] for d in docs],
                           'support':{d['id']:packet['material_support'][d['id']] for d in docs}})
        row={'case':sid,'class_pair':old['candidate'],'member_views':old['views'],
             'candidate_documents':len(packet['candidate_materials']),'checks':checks,'all_restored':True}
        write_json(run/'cases'/sid/'restored_materials.json',row);rows.append(row)
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--workers',type=int,default=4);args=p.parse_args();run=args.run.resolve()
    protocol=read_json(run/'protocol.json');previous=Path(protocol['clusters'])
    selected=set(protocol['cases']);cases=[c for c in read_json(FR/'cases.json')['cases']if c['screen_id'] in selected]
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        rows=list(pool.map(verify_case,[(c,run,previous) for c in cases]))
    restored=targeted(run)
    result={'cases':len(rows),'candidate_pairs_unchanged':sum(r['candidate_pairs'] for r in rows),
            'documents_byte_equal':sum(r['documents_byte_equal'] for r in rows),
            'member_views':sum(r['member_views'] for r in rows),
            'linked_member_views':sum(r['linked_member_views'] for r in rows),
            'targeted_cases':restored,'restored_cases':sum(r['all_restored'] for r in restored)}
    write_json(run/'verification.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
