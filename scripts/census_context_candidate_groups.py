"""Frozen, label-free group coverage over the complete old candidate pools."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prototypes.context_candidate_groups import build_catalogue,schedule


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text())
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def run(inventory,output):
    output.mkdir(parents=True,exist_ok=False)
    inputs={case.name:{name:digest(case/name) for name in ('corpus.json','frontend.json','source_pool.json')}
            for case in sorted(inventory.iterdir()) if (case/'source_pool.json').exists()}
    files=['prototypes/context_candidate_groups.py','scripts/census_context_candidate_groups.py',
           'tests/test_context_candidate_groups.py','relation_search/semantic_selection.py',
           'relation_search/impact_selection.py','relation_search/instrument.py',
           'prototypes/singleton_oracle_slots.py','prototypes/assertion_operand_guard.py',
           'anchor_retrieval/syntax.py','anchor_retrieval/graph.py','anchor_retrieval/index.py',
           'relational_gap/frontend.py']
    write(output/'protocol.json',dict(inventory=str(inventory.resolve()),input_sha256=inputs,
        code_sha256={name:digest(ROOT/name) for name in files},selection='all candidates in old source_pool.json; no target labels',
        groups_per_round=16,max_candidates_per_group=4,max_expected_revisions_per_group=1,
        policies=['shape','impact'],rounds=2,provider_calls=0,subject_executions=0,
        interpretation='candidate exposure in bounded questions, not equal model cost, semantic equivalence or target detection'))
    for name in files:
        destination=output/'code_snapshot'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((ROOT/name).read_bytes())
    summaries={}
    for case in inputs:
        start=time.monotonic();source=inventory/case
        catalogue=build_catalogue(read(source/'corpus.json'),read(source/'frontend.json'),read(source/'source_pool.json')['candidates'])
        write(output/case/'catalogue.json',catalogue)
        summary=dict(input_candidates=catalogue['input_count'],eligible_candidates=catalogue['eligible_count'],
                     contexts=len(catalogue['contexts']),policies={})
        for policy in ('shape','impact'):
            state=None;rounds=[]
            for index in range(2):
                result=schedule(catalogue,budget=16,max_group_size=4,policy=policy,previous=state)
                write(output/case/policy/('round_'+str(index)+'.json'),result)
                rounds.append(dict(groups=result['selected_group_count'],candidates=result['selected_candidate_count'],
                    accumulated_shown=len(result['frontier']['shown_ids']),pending=len(result['pending_ids']),
                    observed_source_obligations=len(result['frontier']['shown_observation_ids'])))
                state=result['frontier']
            summary['policies'][policy]=rounds
        summary['elapsed_seconds']=round(time.monotonic()-start,3)
        summaries[case]=summary
        print(json.dumps(dict(case=case,**summary)),flush=True)
    write(output/'summary.json',summaries)
    write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--inventory',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();run(args.inventory,args.output)
