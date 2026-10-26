#!/usr/bin/env python3
"""Offline candidate/input census. Never opens provider completions or labels."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prototypes.exact_oracle_material import MaterialIndex, POLICY, VERSION, request_keys, select_unique, sha, summarize
from relation_search.impact_selection import select

CODE_PATHS = ['prototypes/exact_oracle_material.py', 'scripts/census_exact_oracle_material.py',
    'relation_search/impact_selection.py', 'relation_search/semantic_selection.py',
    'relation_search/instrument.py', 'relation_search/oracle.py',
    'relation_search/oracle_evidence.py', 'prototypes/singleton_oracle_slots.py',
    'prototypes/assertion_operand_guard.py', 'generic_composition/emitter.py']


def read(path):
    return json.loads(Path(path).read_text())


def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True)+'\n')


def identity(path):
    path=Path(path)
    return dict(path=str(path.resolve()),sha256=sha(path.read_bytes()))


def compare_prefix(records,budget):
    original=records[:budget]
    revised=select_unique(records,budget=budget)
    chosen=revised['selected']
    old_ids={r['id'] for r in original}
    return dict(budget=budget,original=summarize(original),deduplicated=summarize(chosen),
        original_ids=[r['id'] for r in original],deduplicated_ids=[r['id'] for r in chosen],
        incoming_ids=[r['id'] for r in chosen if r['id'] not in old_ids],
        skipped_duplicate_ids=revised['skipped_ids'],
        inspected_eligible_ranks=len(chosen)+len(revised['skipped_ids']))


def ordered_records(index,candidates,ranking):
    by_id={c['id']:c for c in candidates}
    if len(by_id)!=len(candidates):
        raise ValueError('duplicate candidate identifiers')
    if set(by_id)!={r['id'] for r in ranking}:
        raise ValueError('ranking/candidate inventory mismatch')
    records=[]
    for row in ranking:
        evidence=row.get('evidence',{})
        value=index.record(by_id[row['id']],impact_evidence=evidence)
        value.update(rank=row['rank'],eligible=bool(evidence.get('eligible')),
                     family=by_id[row['id']].get('operator',by_id[row['id']].get('kind')))
        records.append(value)
    return records


def pool_case(case,pool,source,output,budget):
    start=time.monotonic()
    paths={name:source/case/(name+'.json') for name in ['corpus','frontend']}
    paths['pool']=pool/case/'source_pool.json'
    corpus,frontend=read(paths['corpus']),read(paths['frontend'])
    candidates=read(paths['pool'])['candidates']
    ranking=select(corpus,frontend,candidates,budget=len(candidates))
    records=ordered_records(MaterialIndex(case,corpus,frontend),candidates,ranking['ranking'])
    eligible=[r for r in records if r['eligible']]
    result=dict(case=case,inputs={k:identity(p) for k,p in paths.items()},
        total=summarize(records),eligible=summarize(eligible),prefix=compare_prefix(eligible,budget),
        policy=ranking['policy'],policy_sha256=ranking['policy_sha256'],elapsed_seconds=time.monotonic()-start)
    write(output/case/'pool_records.json',records)
    write(output/case/'pool_summary.json',result)
    return result


def main_case(case,campaign,output,budget):
    start=time.monotonic()
    base=campaign/case/'round_000'/'semantic'
    # The contents contain outcomes and are deliberately not read.
    if not (base/'semantic_result.json').is_file():
        return dict(case=case,status='semantic_batch_not_complete')
    paths={name:base/(name+'.json') for name in ['corpus','frontend','semantic_selection','semantic_frontier']}
    corpus,frontend=read(paths['corpus']),read(paths['frontend'])
    selection,frontier=read(paths['semantic_selection']),read(paths['semantic_frontier'])
    index=MaterialIndex(case,corpus,frontend)
    records=ordered_records(index,frontier['candidates'],selection['ranking'])
    by_id={r['id']:r for r in records}
    requests=[]
    for path in sorted((base/'requests').glob('request_[0-9][0-9][0-9].json')):
        request=read(path)
        offered=request.get('offered',{})
        if set(offered)!={'C0'}:
            raise ValueError('expected canonical singleton request: '+str(path))
        candidate=offered['C0']['candidate']
        original=by_id[candidate['id']]
        # Confirm source candidate in the offered interface is the frozen one.
        catalogue=next(c for c in frontier['candidates'] if c['id']==candidate['id'])
        if candidate!=catalogue:
            raise ValueError('offered candidate differs from frontier: '+str(path))
        keys=request_keys(request)
        requests.append(dict(original,**keys,request=identity(path),
            actual_safe_key=sha([original['material_key'],keys['oracle_context_key']])))
    if {r['id'] for r in requests}!=set(selection['offered_ids']):
        raise ValueError('actual request inventory differs from frozen offered IDs')
    contexts=defaultdict(set)
    for r in requests:
        contexts[r['material_key']].add(r['oracle_context_key'])
    mismatches=[key for key,values in contexts.items() if len(values)>1]
    eligible=[r for r in records if r['eligible'] and not
              next(v for v in selection['ranking'] if v['id']==r['id']).get('previously_selected',False)]
    result=dict(case=case,status='complete_input_census',inputs={k:identity(p) for k,p in paths.items()},
        queue=summarize(records),actual=summarize(requests),actual_requests=len(requests),
        actual_exact_wire_classes=len({r['wire_key'] for r in requests}),
        actual_oracle_context_classes=len({r['oracle_context_key'] for r in requests}),
        actual_safe_classes=len({r['actual_safe_key'] for r in requests}),
        equivalent_key_but_different_request_context=mismatches,
        prefix=compare_prefix(eligible,budget),elapsed_seconds=time.monotonic()-start)
    write(output/case/'main_queue_records.json',records)
    write(output/case/'main_request_records.json',requests)
    write(output/case/'main_summary.json',result)
    return result


def aggregate(rows,which):
    total=Counter()
    for row in rows:
        if which=='pool':
            total.update(candidate_count=row['total']['candidate_count'],
                program_classes=row['total']['program_classes'],material_classes=row['total']['material_classes'],
                eligible_candidates=row['eligible']['candidate_count'],
                eligible_material_classes=row['eligible']['material_classes'],
                original_budget_slots=row['prefix']['original']['candidate_count'],
                original_program_classes=row['prefix']['original']['program_classes'],
                original_material_classes=row['prefix']['original']['material_classes'],
                deduplicated_material_classes=row['prefix']['deduplicated']['material_classes'],
                incoming_candidates=len(row['prefix']['incoming_ids']),
                unmaterializable=row['total']['unmaterializable'])
        elif row.get('status')=='complete_input_census':
            total.update(completed_cases=1,actual_requests=row['actual_requests'],
                actual_program_classes=row['actual']['program_classes'],
                actual_material_classes=row['actual']['material_classes'],
                actual_exact_wire_classes=row['actual_exact_wire_classes'],
                actual_oracle_context_classes=row['actual_oracle_context_classes'],
                actual_safe_classes=row['actual_safe_classes'],
                mismatched_classes=len(row['equivalent_key_but_different_request_context']),
                queue_prefix_original_material_classes=row['prefix']['original']['material_classes'],
                queue_prefix_deduplicated_material_classes=row['prefix']['deduplicated']['material_classes'],
                queue_prefix_incoming_candidates=len(row['prefix']['incoming_ids']))
    return dict(total)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool-root',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--budget',type=int,default=16)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/'manifest.json').exists():
        raise ValueError('output already initialized; choose a new snapshot directory')
    manifest=dict(version=VERSION,policy=POLICY,budget=args.budget,
        started_utc=datetime.now(timezone.utc).isoformat(),
        code_identity={path:sha((ROOT/path).read_bytes()) for path in CODE_PATHS},
        sources=dict(pool=str(args.pool_root.resolve()),source=str(args.source_root.resolve()),
                     campaign=str(args.campaign.resolve())))
    write(args.output/'manifest.json',manifest)
    for path in CODE_PATHS:
        dest=args.output/'code_snapshot'/path;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes((ROOT/path).read_bytes())
    pool_rows,main_rows=[],[]
    for case in sorted(p.name for p in args.pool_root.iterdir() if (p/'source_pool.json').is_file()):
        pooled=pool_case(case,args.pool_root,args.source_root,args.output,args.budget)
        pool_rows.append(pooled)
        actual=main_case(case,args.campaign,args.output,args.budget)
        main_rows.append(actual)
        report=dict(manifest=manifest,pool=pool_rows,main=main_rows,
            pool_totals=aggregate(pool_rows,'pool'),main_totals=aggregate(main_rows,'main'))
        write(args.output/'report.json',report)
        print(json.dumps(dict(case=case,pool=pooled['total']['candidate_count'],
            original_unique=pooled['prefix']['original']['material_classes'],
            selected_unique=pooled['prefix']['deduplicated']['material_classes'],
            main_requests=actual.get('actual_requests'),main_unique=actual.get('actual_safe_classes')),sort_keys=True),flush=True)
    report['finished_utc']=datetime.now(timezone.utc).isoformat()
    write(args.output/'report.json',report)
    print(json.dumps(dict(pool=report['pool_totals'],main=report['main_totals']),sort_keys=True),flush=True)


if __name__=='__main__':
    main()
