"""Blind, source-only comparison of original and reparsed observation graphs."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experimental.modified_observation_impact import select
from relation_search.impact_selection import select as production_select


FILES=['experimental/modified_observation_impact.py','tests/test_modified_observation_impact.py',
    'scripts/census_modified_observation_impact.py','relation_search/impact_selection.py',
    'relation_search/semantic_selection.py','relation_search/oracle_evidence.py','relation_search/instrument.py',
    'experimental/singleton_oracle_slots.py','experimental/assertion_operand_guard.py',
    'anchor_retrieval/index.py','anchor_retrieval/graph.py','anchor_retrieval/syntax.py',
    'relational_gap/frontend.py','generic_composition/corpus.py']


def read(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def summary(result):
    evidence=[r['evidence'] for r in result['ranking']]
    return dict(inputs=result['input_count'],eligible=result['eligible_count'],selected=result['selected_count'],
        candidates_with_obligations=sum(bool(r['obligations']) for r in evidence),
        obligations=sum(len(r['obligations']) for r in evidence),
        balanced_observations=sum(len(r['balanced_observation_ids']) for r in evidence),
        graph_builds=result.get('graph_builds'),graph_cache_hits=result.get('graph_cache_hits'),
        unknown_reasons=dict(Counter(reason.split(':',1)[0] for r in evidence for reason in r['unknowns'])))


def run(inventory,output):
    output.mkdir(parents=True,exist_ok=False)
    inputs={case.name:{name:dict(path=str((case/name).resolve()),sha256=digest(case/name))
        for name in ('corpus.json','frontend.json','source_pool.json')}
        for case in sorted(inventory.iterdir()) if (case/'source_pool.json').exists()}
    hashes={name:digest(ROOT/name) for name in FILES}
    write(output/'protocol.json',dict(inventory=str(inventory.resolve()),inputs=inputs,code_sha256=hashes,
        arms=['production_original','owner_original','owner_modified'],budget_per_case=16,
        selection='all saved source_pool candidates; no target, cache, model or runtime inputs',
        control='owner_original and owner_modified share scope, original edit ports, source observation IDs and greedy ranking',
        production_reference='different legacy port identity and original multi-file test index scope; do not attribute every difference to reparsing',
        provider_calls=0,subject_executions=0))
    for name in FILES:
        destination=output/'code_snapshot'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((ROOT/name).read_bytes())
    summaries={}
    for case,paths in inputs.items():
        corpus=read(Path(paths['corpus.json']['path']));front=read(Path(paths['frontend.json']['path']))
        pool=read(Path(paths['source_pool.json']['path']))['candidates'];results={};stats={}
        for arm in ('production_original','owner_original','owner_modified'):
            start=time.monotonic()
            result=(production_select(corpus,front,pool,budget=16) if arm=='production_original' else
                    select(corpus,front,pool,budget=16,graph_source=arm.removeprefix('owner_')))
            write(output/case/(arm+'.json'),result);results[arm]=result
            stats[arm]=dict(summary(result),elapsed_seconds=round(time.monotonic()-start,3))
            print(json.dumps(dict(case=case,arm=arm,**stats[arm])),flush=True)
        def pairs(row):return {(o['observation_id'],o['port_id']) for o in row['evidence']['obligations']}
        before={r['id']:r for r in results['owner_original']['ranking']}
        after={r['id']:r for r in results['owner_modified']['ranking']}
        assert before.keys()==after.keys()=={c['id'] for c in pool}
        changes=[dict(id=cid,old_rank=before[cid]['rank'],new_rank=after[cid]['rank'],
                      gained=len(pairs(after[cid])-pairs(before[cid])),lost=len(pairs(before[cid])-pairs(after[cid])))
                 for cid in sorted(before)]
        write(output/case/'obligation_changes.json',changes)
        stats['graph_comparison']=dict(candidates_gaining_obligations=sum(r['gained']>0 for r in changes),
            candidates_losing_obligations=sum(r['lost']>0 for r in changes),
            new_selected_ids=len({c['id'] for c in results['owner_modified']['selected']}
                                -{c['id'] for c in results['owner_original']['selected']}))
        summaries[case]=stats
        if any(digest(Path(row['path']))!=row['sha256'] for row in paths.values()):
            raise ValueError('source inputs changed during census')
    write(output/'summary.json',summaries)
    if {name:digest(ROOT/name) for name in FILES}!=hashes:
        raise ValueError('analysis changed during census; no seal')
    write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return dict(cases=len(summaries),summary=str((output/'summary.json').resolve()))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.inventory,args.output)))
