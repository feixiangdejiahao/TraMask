"""Frozen, label-free sample census of candidate-specific oracle source evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.oracle_evidence import build_evidence


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source, inventory, output, samples=8):
    output.mkdir(parents=True, exist_ok=False)
    cases = sorted(path.parent.name for path in source.glob('*/corpus.json') if (inventory/path.parent.name/'candidates.json').exists())
    inputs = {}
    for case in cases:
        paths = [source/case/'corpus.json', source/case/'frontend.json', inventory/case/'candidates.json']
        inputs[case] = {str(p.resolve()):digest(p) for p in paths}
    code_paths = [ROOT/p for p in ['relation_search/oracle_evidence.py', 'scripts/census_oracle_evidence.py',
        'relational_gap/frontend.py', 'anchor_retrieval/syntax.py', 'anchor_retrieval/index.py',
        'anchor_retrieval/graph.py', 'relation_search/instrument.py']]
    write(output/'protocol.json', dict(source=str(source.resolve()), inventory=str(inventory.resolve()),
        cases=cases, samples_per_case=samples, sampling='SHA256(candidate.id), first N; no labels or oracle cache',
        input_sha256=inputs, code_sha256={str(p.relative_to(ROOT)):digest(p) for p in code_paths},
        provider_calls=0, subject_executions=0, max_evidence_bytes=48000))
    for path in code_paths:
        destination = output/'code_snapshot'/path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    summary = {}
    for case in cases:
        corpus = read(source/case/'corpus.json')
        frontend = read(source/case/'frontend.json')
        pool = read(inventory/case/'candidates.json')['candidates']
        selected = sorted((c for c in pool if not c.get('is_source_profile')),
                          key=lambda c:hashlib.sha256(c['id'].encode()).hexdigest())[:samples]
        records = []
        for candidate in selected:
            start = time.monotonic()
            try:
                evidence = build_evidence(corpus, frontend, candidate)
                write(output/case/(candidate['id']+'.json'), evidence)
                records.append(dict(candidate_id=candidate['id'], status=evidence['status'],
                    context_bytes=evidence['rendered_bytes'], seed_calls=len(evidence['seed_call_ids']),
                    related_assertions=len(evidence['assertions']), calls=len(evidence['calls']),
                    resolved_calls=sum(bool(c['targets']) for c in evidence['calls']),
                    actual_formal=sum(len(c['actual_formal']) for c in evidence['calls']),
                    full_declarations=len(evidence['declarations']), controls=len(evidence['controls']),
                    field_state_edges=sum(e['kind']=='same_local_binding_after_field_write_may' for e in evidence['edges']),
                    unknown_reasons=sorted({u['reason'] for u in evidence['unknowns']}),
                    elapsed_seconds=round(time.monotonic()-start,3)))
            except (ValueError, KeyError) as error:
                records.append(dict(candidate_id=candidate['id'],status='analysis_error', error=str(error),
                                    elapsed_seconds=round(time.monotonic()-start,3)))
        write(output/case/'records.json', records)
        sizes = sorted(r['context_bytes'] for r in records if 'context_bytes' in r)
        summary[case] = dict(pool=len(pool), sampled=len(records), errors=sum(r['status']=='analysis_error' for r in records),
            ready=sum(r['status']=='ready' for r in records), over_budget=sum(r['status']=='over_budget' for r in records),
            with_call_link=sum(r.get('seed_calls',0)>0 for r in records),
            with_assertion_link=sum(r.get('related_assertions',0)>0 for r in records),
            with_resolved_callee=sum(r.get('resolved_calls',0)>0 for r in records),
            with_source_control=sum(r.get('controls',0)>0 for r in records),
            field_state_edges=sum(r.get('field_state_edges',0) for r in records),
            bytes=dict(min=min(sizes,default=0),median=sizes[len(sizes)//2] if sizes else 0,max=max(sizes,default=0)),
            elapsed_seconds=round(sum(r['elapsed_seconds'] for r in records),3))
        print(json.dumps(dict(case=case,**summary[case])),flush=True)
    write(output/'summary.json',summary)
    write(output/'seal.json', dict(files_sha256={str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=8)
    args=parser.parse_args()
    run(args.source,args.inventory,args.output,args.samples)
