"""Source-only local-helper analysis of every preselected paired member.

Reads the existing paired protocol, ready record and request source records,
never model responses, subject outcomes or evaluation labels. No new selection.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from prototypes.local_helper_evidence import analyze

FILES=['prototypes/local_helper_evidence.py','tests/test_local_helper_evidence.py',
    'scripts/census_local_helper_evidence.py','prototypes/go_assertion_helper.py',
    'prototypes/go_arity_guard.py','relation_search/oracle_evidence.py','relation_search/instrument.py',
    'anchor_retrieval/syntax.py','anchor_retrieval/index.py','anchor_retrieval/graph.py',
    'generic_composition/corpus.py','relational_gap/frontend.py']


def read(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def run(paired,output):
    protocol,ready=read(paired/'protocol.json'),read(paired/'ready.json')
    if digest(paired/'protocol.json')!=ready['protocol_sha256']:
        raise ValueError('paired protocol does not match ready record')
    inventory=Path(protocol['inventory'])
    inputs={str((paired/name).resolve()):digest(paired/name) for name in ['protocol.json','ready.json']}
    for record in ready['records']:
        if record['status']!='offerable':
            continue
        path=Path(record['arms']['template']['request'])
        if digest(path)!=record['arms']['template']['request_sha256']:
            raise ValueError('paired source request changed')
        inputs[str(path.resolve())]=digest(path)
        corpus=inventory/record['case']/'corpus.json'
        if digest(corpus)!=protocol['input_sha256'][record['case']]['corpus.json']:
            raise ValueError('paired corpus changed')
        inputs[str(corpus.resolve())]=digest(corpus)
    output.mkdir(parents=True,exist_ok=False)
    hashes={name:digest(ROOT/name) for name in FILES}
    write(output/'protocol.json',dict(version='local-helper-cohort-v2',paired=str(paired.resolve()),
        inputs_sha256=inputs,code_sha256=hashes,selection='all offered concrete members of all existing paired ready records',
        denominator='local helper-name calls inside these modified complete tests; not a labeled assertion/gap truth set',
        source_call_recovery='match old candidate-specific call span, source code and callee exactly',
        old_capability='existing same-package standard testing guard prototype is reused for Go parameter parsing only',
        new_capability='lexically local def/literal/arrow bindings, per-call actual/formal and assertion expected argument boundaries',
        model_requests=0,subject_executions=0,production_oracle_edits=0,
        forbidden_inputs=['model answers','native test outcomes','target labels','hidden verifier','reference patch']))
    for name in FILES:
        path=output/'code_snapshot'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
    summaries=[];total=Counter();reasons=Counter();port_reasons=Counter()
    for record in ready['records']:
        case=record['case'];rows=[]
        if record['status']=='offerable':
            request=read(Path(record['arms']['template']['request']))
            corpus=read(inventory/case/'corpus.json')
            if [row['candidate']['id'] for row in request['offered'].values()]!=record['member_ids']:
                raise ValueError('paired member inventory changed')
            for alias,offered in request['offered'].items():
                result=analyze(corpus,offered['candidate'])
                write(output/case/(alias+'.json'),result)
                matched=0;newly_bound=0
                for old in request['analysis_evidence'][alias]['calls']:
                    matches=[new for new in result['calls'] if
                        all(new['span'][k]==old['span'][k] for k in ['path','start_byte','end_byte'])
                        and new['code']==old['code'] and new['callee']==old['callee']]
                    if len(matches)==1:
                        matched+=1
                        newly_bound+=int(matches[0]['status']=='resolved' and not old.get('actual_formal'))
                counts=result.get('counts',{})
                rows.append(dict(alias=alias,candidate_id=offered['candidate']['id'],status=result['status'],
                    **counts,old_evidence_exact_call_matches=matched,old_unbound_calls_source_bound_now=newly_bound))
                for key in ['local_bindings','local_helper_name_calls','resolved_calls','assertion_instances','expected_argument_ports']:
                    total[key]+=counts.get(key,0)
                total['members']+=1;total['members_with_local_calls']+=int(bool(result['calls']))
                total['old_unbound_calls_source_bound_now']+=newly_bound
                reasons.update(counts.get('unknown_reasons',{}))
                port_reasons.update(counts.get('expected_port_unknown_reasons',{}))
        summary=dict(case=case,members=rows)
        summaries.append(summary)
        print(json.dumps(dict(case=case,members=len(rows),local_helper_calls=sum(row.get('local_helper_name_calls',0) for row in rows),
            resolved=sum(row.get('resolved_calls',0) for row in rows),expected_argument_ports=sum(row.get('expected_argument_ports',0) for row in rows),
            old_unbound_calls_source_bound_now=sum(row.get('old_unbound_calls_source_bound_now',0) for row in rows))),flush=True)
    final=dict(cases=len(summaries),totals=dict(total),unknown_reasons=dict(reasons),
        expected_port_unknown_reasons=dict(port_reasons),cases_detail=summaries,
        interpretation='source-support census only; no expected correctness, reliable edit, gap detection or resolution-rate claim')
    write(output/'summary.json',final)
    if {name:digest(ROOT/name) for name in FILES}!=hashes or any(digest(Path(path))!=expected for path,expected in inputs.items()):
        raise ValueError('source or code changed during census; no seal')
    write(output/'seal.json',dict(files_sha256={str(path.relative_to(output)):digest(path)
        for path in sorted(output.rglob('*')) if path.is_file()}))
    return final['totals']


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--paired',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(run(args.paired,args.output)))
