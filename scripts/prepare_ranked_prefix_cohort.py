"""Freeze a uniform source-diverse head of an existing all-trial frontier.

The supplied frontier is a previously recorded controlled-failure pool. This
script uses its membership, fixed source ranking, program text and input hashes.
It ignores native messages, semantic decisions and evaluation annotations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.checkpoint import read
from relation_search.source_program_diversity import identity
from scripts.run_contract_repair_search import write,frozen,verify


def prepare(frontier,output,per_case):
    if type(per_case) is not int or per_case<1:raise ValueError('A positive per-case limit is required')
    seal=read(frontier/'seal.json');verify(seal['prepared']);p=read(frontier/'prepared.json')
    verify(p['inventory']);inventory=read(p['inventory']['path'])['controlled_failures']
    by_key={row['key']:row for row in inventory}
    if len(by_key)!=len(inventory):raise ValueError('Ambiguous frontier occurrence')
    cache={};checked={};selected={};logs=[]
    def material(receipt):
        path=receipt['path']
        if path in checked and checked[path]!=receipt['sha256']:raise ValueError('Conflicting input hash')
        if path not in checked:
            verify(receipt);checked[path]=receipt['sha256'];cache[path]=read(path)
        return cache[path]
    for case in p['cases']:
        chosen=[];seen=set();examined=[]
        for rank in case['ranking']:
            row=by_key[rank['key']]
            if row['case']!=case['case'] or row['candidate_id']!=rank['candidate_id']:raise ValueError('Frontier identity mismatch')
            inputs={name:row['inputs'][name] for name in ('corpus','frontend','candidates')}
            corpus=material(inputs['corpus']);material(inputs['frontend']);catalog=material(inputs['candidates'])
            if isinstance(catalog,dict):catalog=catalog['candidates']
            matches=[c for c in catalog if c['id']==rank['candidate_id']]
            if len(matches)!=1:raise ValueError('Source candidate identity is not unique')
            syntax=identity(corpus,matches[0]);key=syntax or 'unresolved:'+rank['key']
            duplicate=key in seen
            examined.append(dict(source_rank=rank['rank'],candidate_id=rank['candidate_id'],syntax_scope=syntax,duplicate=duplicate))
            if duplicate:continue
            seen.add(key);chosen.append(dict(name=case['case']+'_source_'+str(rank['rank']),case=case['case'],
                candidate_id=rank['candidate_id'],source_inputs=inputs,source_rank=rank['rank'],
                source_syntax_scope=syntax,selection_rank=len(chosen)+1))
            if len(chosen)>=per_case:break
        selected[case['case']]=chosen
        logs.append(dict(case=case['case'],available=len(case['ranking']),selected=len(chosen),examined=examined))
    items=[selected[case][rank] for rank in range(per_case) for case in sorted(selected) if rank<len(selected[case])]
    result=dict(version='uniform-distinct-source-prefix-cohort.v1',items=items,selection=logs,
        frontier=frozen(frontier/'prepared.json'),inventory=p['inventory'],per_case=per_case,
        trial_denominator=len(p['cases']),ordering='distinct_source_rank_then_sorted_case',
        criterion='First distinct normalized syntax/scope identities in the frozen source ranking; unresolved identities remain distinct.',
        historical_native_use='Controlled-failure pool membership only; no failure diagnostics or evaluation labels are used.',
        external_model_calls=0,new_native_executions=0)
    write(output,result)
    return dict(cases=len(selected),parents=len(items),cohort=frozen(output))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--frontier',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--per-case',type=int,default=8)
    a=p.parse_args();print(json.dumps(prepare(a.frontier,a.output,a.per_case)))
