"""Offline shared-q comparison and scalar writer evidence, without targets."""
from __future__ import annotations

import argparse
import ast
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experimental.assertion_write_origin import Module
from relation_search.checkpoint import read,write,digest


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'))


def observation_key(row):
    return {name:row.get(name) for name in ['source_q_span','source_q_sha256',
        'source_allocation_span','source_allocation_sha256','class_id','field','observed_field']}


def compare_shared(smoke):
    results=[]
    for selected in read(smoke/'protocol.json')['selected']:
        case=selected['case']
        grouped={}
        evidence={}
        for role in ['control','generated']:
            path=smoke/case/'execution'/role/'observed_writes.jsonl'
            evidence[str(path.resolve())]=digest(path)
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            q=defaultdict(list)
            for row in rows:
                if row['kind']=='assertion_read' and row.get('source_q_span'):
                    q[canonical(observation_key(row))].append(row)
            grouped[role]=q
        common=sorted(set(grouped['control'])&set(grouped['generated']))
        comparisons=[]
        for key in common:
            a,b=grouped['control'][key],grouped['generated'][key]
            valid=lambda rows:[row for row in rows if row['status']=='observed_within_instrumented_code']
            av,bv=valid(a),valid(b)
            writers=lambda rows:{canonical([r.get('source_last_observed_writer'),r.get('source_last_observed_writer_sha256')]) for r in rows}
            values=lambda rows:{canonical(r['value']) for r in rows}
            pair=lambda rows:{canonical([r.get('source_last_observed_writer'),r['value']]) for r in rows}
            comparisons.append(dict(identity=json.loads(key),control_observations=len(a),generated_observations=len(b),
                valid_control_observations=len(av),valid_generated_observations=len(bv),
                comparable=bool(av and bv),control_states=[json.loads(x) for x in sorted(pair(av))],
                generated_states=[json.loads(x) for x in sorted(pair(bv))],
                new_writer_count=len(writers(bv)-writers(av)) if av and bv else None,
                new_value_count=len(values(bv)-values(av)) if av and bv else None,
                new_state_count=len(pair(bv)-pair(av)) if av and bv else None,
                unknown_reasons=dict(Counter(r['reason'] for r in [*a,*b] if r['status']=='unknown'))))
        results.append(dict(case=case,shared_q=len(common),comparable_shared_q=sum(x['comparable'] for x in comparisons),
            shared_q_with_new_writer=sum(bool(x['new_writer_count']) for x in comparisons),
            shared_q_with_new_value=sum(bool(x['new_value_count']) for x in comparisons),
            fields=dict(Counter(x['identity']['field'] for x in comparisons)),
            comparisons=comparisons,evidence_sha256=evidence,correctness_evaluated=False))
    return results


def scalar_inventory(overlay):
    rows=[]
    for group in read(overlay/'summary.json')['groups']:
        manifest=read(group['manifest'])
        original=read(manifest['observation_overlay']['source_manifest'])
        corpus=read(Path(original['original_input'])/'corpus.json')
        modules={}
        phases=[]
        for phase in group['phases']:
            plan=read(phase['instrumentation'])
            fields=[]
            for cls,field in sorted({(q['class_id'],q['storage_field']) for q in plan['queries']}):
                writers=[]
                for site in plan['writes']:
                    if (site['class_id'],site['storage_field'])!=(cls,field):continue
                    span=site['source_writer_span'];path=span['path']
                    if path not in modules:
                        code=corpus['sources'][path]['code']
                        modules[path]=Module(path,code,ast.parse(code))
                    module=modules[path]
                    node=next(n for n in ast.walk(module.tree)
                        if isinstance(n,(ast.Assign,ast.AnnAssign,ast.AugAssign)) and module.span(n)==span)
                    try:
                        value=ast.literal_eval(node.value)
                        scalar=type(value) in {bool,int,float,str,bytes,type(None)}
                    except (ValueError,TypeError,SyntaxError):
                        value,scalar=None,False
                    writers.append(dict(source_span=span,scalar_literal=scalar,
                        scalar_type=type(value).__name__ if scalar else None,
                        expression=module.text(node.value)))
                count=sum(q['class_id']==cls and q['storage_field']==field for q in plan['queries'])
                fields.append(dict(class_id=cls,field=field,mapped_q_count=count,writers=writers,
                    evidence='all_tracked_writers_scalar_literals' if writers and all(w['scalar_literal'] for w in writers)
                    else 'some_tracked_writers_scalar_literals' if any(w['scalar_literal'] for w in writers)
                    else 'no_tracked_scalar_literal_writer'))
            phases.append(dict(role=phase['role'],mapped_q=len(plan['queries']),fields=fields,
                scalar_literal_writer_q=sum(row['mapped_q_count'] for row in fields
                    if row['evidence']=='all_tracked_writers_scalar_literals')))
        rows.append(dict(case=group['case'],manifest=group['manifest'],phases=phases))
    return dict(groups=rows,scope='all mapped q in all overlay groups; no execution or target selection',
        interpretation='Literal writer syntax is source evidence, not proof of runtime scalar value or complete external write coverage.')


def audit(overlay,smoke,output):
    output.mkdir(parents=True,exist_ok=False)
    write(output/'shared_q_comparison.json',compare_shared(smoke))
    write(output/'scalar_writer_inventory.json',scalar_inventory(overlay))
    # The source compilation audit was appended after launch. Recover the exact
    # pre-audit seal by hash, preserving the launch receipt instead of rewriting it.
    old=read(overlay/'seal.json')
    old['files_sha256'].pop('source_audit.json',None)
    prior=(json.dumps(old,sort_keys=True,indent=2)+'\n').encode()
    requested=read(smoke/'protocol.json')['overlay_seal_sha256']
    if hashlib.sha256(prior).hexdigest()!=requested:
        raise ValueError('Cannot reconstruct exact launch overlay seal')
    (output/'overlay_seal_at_launch.json').write_bytes(prior)
    write(output/'provenance.json',dict(launch_overlay_seal_sha256=requested,
        post_execution_audited_overlay_seal_sha256=digest(overlay/'seal.json'),
        appended_file='source_audit.json',all_launch_source_artifacts_unchanged=True,
        smoke_protocol_sha256=digest(smoke/'protocol.json'),script_sha256=digest(Path(__file__))))
    for relative,checksum in old['files_sha256'].items():
        if digest(overlay/relative)!=checksum:raise ValueError('Launch artifact changed')
    write(output/'seal.json',dict(files_sha256={str(p.relative_to(output)):digest(p)
        for p in output.rglob('*') if p.is_file() and p.name!='seal.json'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--overlay',type=Path,required=True)
    parser.add_argument('--smoke',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    audit(args.overlay,args.smoke,args.output)
