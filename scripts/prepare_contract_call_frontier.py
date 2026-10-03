"""Freeze source-only edited-contract-call rankings, without evaluating labels."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from relation_search.admission import program_candidate
from relation_search import edited_contract_call_priority as priority
from relation_search import semantic_selection
from scripts.evaluate_test_validity import digest, loaded_local_sources, read, verify_seal, write_new


def prepare(input_path,output,*,limits=(16,32,64),selector=priority,frontend_refresher=None):
    if any(type(limit) is not int or limit<0 for limit in limits):raise ValueError('nonnegative integer limits required')
    # No other inventory section is read by this selector.
    records=read(input_path)['controlled_failures'];by_case=defaultdict(list)
    for row in records:by_case[row['case']].append(row)
    output.mkdir(parents=True,exist_ok=False)
    algorithm=loaded_local_sources()
    protocol=dict(policy=selector.POLICY,policy_sha256=selector.digest(selector.POLICY),
        algorithm=algorithm,limits=list(limits),source_inventory=dict(path=str(input_path.resolve()),sha256=digest(input_path)),
        input_section='controlled_failures only',evaluation_labels_used=False,
        runtime_outcomes_used_only_for_initial_failing_pool=True,native_failure_text_used=False,
        provider_calls=0,native_executions=0)
    if frontend_refresher:
        protocol['frontend_refresh']=frontend_refresher.VERSION
    write_new(output/'protocol.json',protocol)
    selected={limit:[] for limit in limits};cases=[];inputs=[];started=time.monotonic()
    for case,rows in sorted(by_case.items()):
        identities={(row['inputs']['corpus']['sha256'],row['inputs']['frontend']['sha256']) for row in rows}
        if len(identities)!=1:raise ValueError('one frozen corpus/frontend snapshot required per task')
        candidates={};occurrences={};cache={};source=None;frontend=None
        for row in rows:
            receipts=row['inputs'];paths=tuple(receipts[name]['path'] for name in ('corpus','frontend','candidates'))
            for name,path in zip(('corpus','frontend','candidates'),paths):
                if path not in cache:
                    if digest(path)!=receipts[name]['sha256']:raise ValueError('frozen input source changed')
                    cache[path]=read(path);inputs.append(dict(path=path,sha256=receipts[name]['sha256']))
            source=cache[paths[0]];frontend=cache[paths[1]]
            table=cache.setdefault(('candidate_map',paths[2]),{c['id']:c for c in cache[paths[2]]})
            candidate=program_candidate(table[row['candidate_id']]);identifier=candidate['id']
            if identifier in candidates and semantic_selection._material(candidates[identifier])!=semantic_selection._material(candidate):
                raise ValueError('one candidate identity has different program material')
            candidates[identifier]=candidate;occurrences.setdefault(identifier,row)
        corpus_path=Path(rows[0]['inputs']['corpus']['path']);issue_path=corpus_path.with_name('issue.md')
        issue=issue_path.read_text();issue_receipt=dict(path=str(issue_path.resolve()),sha256=digest(issue_path))
        inputs.append(issue_receipt)
        case_started=time.monotonic()
        refreshed=None
        if frontend_refresher:
            frontend=frontend_refresher.refresh(source,frontend)
            path=output/'refreshed_frontends'/(case+'.json')
            write_new(path,frontend)
            refreshed=dict(path=str(path.resolve()),sha256=digest(path),stats=frontend['stats'])
        allocation=selector.select(source,frontend,list(candidates.values()),issue,budget=0)
        ranked_ids=[row['id'] for row in allocation['ranking']]
        for limit in limits:selected[limit].extend(occurrences[identifier] for identifier in ranked_ids[:limit])
        case_record=dict(case=case,candidates=len(candidates),issue=issue_receipt,
            issue_names=allocation['issue_names'],feature_true=sum(row['contract_call']['feature'] for row in allocation['ranking']),
            status_counts=dict(Counter(row['contract_call']['status'] for row in allocation['ranking'])),
            source_analysis_seconds=time.monotonic()-case_started,
            ranking=allocation['ranking'],policy_sha256=allocation['policy_sha256'],baseline_policy_sha256=allocation['baseline_policy_sha256'])
        if refreshed:case_record['refreshed_frontend']=refreshed
        write_new(output/(case+'.json'),case_record)
        cases.append({key:value for key,value in case_record.items() if key!='ranking'})
        print(json.dumps(cases[-1]),flush=True)
    verify_seal(algorithm)
    if set(loaded_local_sources())-set(algorithm):raise ValueError('unsealed source imported during selection')
    artifacts=[]
    for limit in limits:
        destination=output/('selected_'+str(limit)+'.json')
        write_new(destination,dict(version=selector.POLICY['version'],controlled_failures=selected[limit],
            source_inventory=protocol['source_inventory'],source_only_ranking=True,
            selected_without_positive_or_review_labels=True,per_case=limit,unselected_status='pending_admission_budget'))
        artifacts.append(dict(limit=limit,path=str(destination.resolve()),sha256=digest(destination),selected=len(selected[limit])))
    summary=dict(protocol=protocol,cases=cases,source_inputs=inputs,selected_inventories=artifacts,
        input_occurrences=len(records),ranked_candidates=sum(row['candidates'] for row in cases),
        feature_true=sum(row['feature_true'] for row in cases),elapsed_seconds=time.monotonic()-started,
        interpretation='A frozen source priority only, not validity or detection; no target matching performed.')
    write_new(output/'manifest.json',summary)
    return {key:summary[key] for key in ('input_occurrences','ranked_candidates','feature_true','elapsed_seconds')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limits',type=int,nargs='+',default=[16,32,64])
    args=parser.parse_args()
    print(json.dumps(prepare(args.input,args.output,limits=tuple(args.limits))))
