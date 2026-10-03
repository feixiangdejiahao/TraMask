"""Compare value interfaces and reasoning settings on a frozen first-rank cohort."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import expected_slots,literal_value_slots,oracle_constant_mask
from relation_search.checkpoint import read,digest
from relational_gap.provider import dispatch
from scripts.run_contract_repair_search import frozen,verify,write
from scripts import run_test_admission as admission


def prepare(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False)
    verify(read(args.source/'seal.json'));source=read(args.source/'prepared.json');items=[];excluded=[]
    for case in source['cases']:
        directory=args.source/'cases'/case['case']/'candidate_0001/derivation'
        if not (directory/'analysis.json').exists():raise ValueError('First-rank preparation incomplete')
        if not (directory/'request.json').exists():
            excluded.append(dict(case=case['case'],reason=read(directory/'analysis.json')['status']));continue
        original=read(directory/'request.json')
        corpus_receipt=case['source_inputs']['corpus.json']
        verify(corpus_receipt);corpus=read(corpus_receipt['path'])
        for arm in ('raw_enabled','values_disabled','values_enabled'):
            request=(literal_value_slots.from_raw(original,corpus) if arm.startswith('values') else dict(original))
            request.update(thinking='disabled' if arm.endswith('disabled') else 'enabled',
                max_tokens=4096 if arm.endswith('disabled') else 16384,reasoning_effort='high')
            fields={k:request[k] for k in ('system','prompt','thinking','max_tokens','reasoning_effort')}
            request['id']=hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            path=root/f'item_{len(items):04d}'/'request.json';write(path,request)
            items.append(dict(case=case['case'],arm=arm,request=frozen(path),corpus=corpus_receipt,
                raw_request=frozen(directory/'request.json'),raw_decision=frozen(directory/'decision.json'),
                cohort_selection='every_trial_first_rank_with_prepared_slots_before_any_label_audit'))
    for module in (expected_slots,literal_value_slots,oracle_constant_mask):admission._preload_local_imports(module)
    protocol=dict(items=items,excluded=excluded,source=frozen(args.source/'prepared.json'),
        algorithm=admission._loaded_sources(),max_calls=args.max_calls,max_total_tokens=args.max_total_tokens,
        deadline_utc=args.deadline_utc,component_only=True,native_executions=0,
        evaluation_labels_used=False,native_outcomes_sent_to_provider=False)
    write(root/'prepared.json',protocol);write(root/'seal.json',frozen(root/'prepared.json'))
    return dict(requests=len(items),excluded=excluded)


def run(args):
    root=args.input
    with (root/'.run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verify(read(root/'seal.json'));protocol=read(root/'prepared.json');admission.verify_seal(protocol['algorithm'])
        deadline=datetime.fromisoformat(protocol['deadline_utc'].replace('Z','+00:00'))
        results=[];calls=tokens=0;corpora={}
        for item in protocol['items']:
            verify(item['request']);request=read(item['request']['path']);directory=Path(item['request']['path']).parent
            reservation=len(request['system'].encode())+len(request['prompt'].encode())+request['max_tokens']+1024
            if (directory/'completion/manifest.json').exists():
                receipt=read(directory/'completion/manifest.json')
                if receipt['status'] in {'prepared','dispatching'}:raise ValueError('Audit interrupted dispatch before resume')
            else:
                if (calls>=protocol['max_calls'] or tokens+reservation>protocol['max_total_tokens']
                        or (deadline-datetime.now(timezone.utc)).total_seconds()<300):break
                receipt=dispatch(request,directory/'completion',root=ROOT)
            calls+=receipt['external_model_calls'];usage=(receipt.get('usage') or {}).get('total_tokens')
            tokens+=usage if type(usage) is int and usage>=0 else reservation
            key=item['corpus']['path']
            if key not in corpora:verify(item['corpus']);corpora[key]=read(key)
            method=literal_value_slots if item['arm'].startswith('values') else expected_slots
            result=(method.validate(request,(directory/'completion/completion.txt').read_text(),corpora[key],
                      finish_reason=receipt.get('finish_reason')) if receipt['status']=='complete'
                    else dict(status='unknown',candidate=None,reason='provider_error'))
            candidate=result.pop('candidate');write(directory/'decision.json',result)
            if candidate is not None:write(directory/'candidate.json',candidate)
            results.append(dict(**item,decision=result,provider_finish=receipt.get('finish_reason'),
                measured_tokens=usage,candidate=frozen(directory/'candidate.json') if candidate else None))
            print(json.dumps(dict(case=item['case'],arm=item['arm'],status=result['status'],
                                  reason=result.get('reason'),calls=calls,tokens=tokens)),flush=True)
        admission.verify_seal(protocol['algorithm'])
        summary=dict(results=results,pending=len(protocol['items'])-len(results),provider_calls=calls,
            tokens=tokens,component_only=True,completed_utc=datetime.now(timezone.utc).isoformat())
        write(root/'summary.json',summary)
        return {k:v for k,v in summary.items() if k!='results'}


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('stage',choices=['prepare','run'])
    p.add_argument('--source',type=Path);p.add_argument('--input',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--max-calls',type=int,default=48);p.add_argument('--max-total-tokens',type=int,default=1400000)
    p.add_argument('--deadline-utc',default='2026-10-03T18:30:00Z')
    args=p.parse_args();print(json.dumps(prepare(args) if args.stage=='prepare' else run(args)))
