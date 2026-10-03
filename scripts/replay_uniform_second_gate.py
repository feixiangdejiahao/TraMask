"""Replay one uniform second gate over a fixed detector's first alerts.

All trials remain in the denominator. Rejected alerts are never replaced with
another candidate. Cached reviews apply only to the identical complete source
payload, plus the explicitly allowed API documentation context. Labels and
manual audits are not inputs. This is retrospective development-set evidence,
not a fresh end-to-end experiment or a generalization result.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import compact_admission
from relation_search.checkpoint import read
from scripts.run_contract_repair_search import write,frozen,verify


VERSION='exact-payload-second-gate-replay.v1'


def compatible(first,second):
    if first['candidate_sha256']!=second['candidate_sha256']:return 'candidate_program_changed'
    if first['system']!=second['system']:return 'review_semantics_changed'
    if (second.get('thinking')!='enabled' or second.get('reasoning_effort')!='high'
            or second.get('max_tokens')!=16384):return 'different_second_gate_configuration'
    before=json.loads(first['prompt']);after=json.loads(second['prompt'])
    # The second gate's declared evidence addition is documentation/types only.
    # No runtime outcomes, repaired programs or different helper graphs qualify.
    after.pop('api_contract_context',None);before.pop('api_contract_context',None)
    if before!=after:return 'complete_source_payload_changed'
    if first['check_ids']!=second['check_ids']:return 'acceptance_obligations_changed'
    for path,sha in second['source_sha256'].items():
        if first['source_sha256'].get(path)!=sha:return 'source_inventory_changed'
    if not second.get('no_execution_outcomes') or not second.get('no_evaluation_labels'):
        return 'provider_evidence_roles_unconfirmed'
    return None


def prepare(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False)
    baseline=read(args.baseline/'summary.json');first=read(args.baseline/'prepared.json')
    reviews=read(args.reviews/'prepared.json');by={row['key']:row for row in reviews['entries']}
    attempts={read(p)['selection']['key']:p.parent for p in args.baseline.glob('attempts/*/result.json')}
    items=[]
    for alert in baseline['outputs']:
        record=dict(case=alert['case'],candidate_id=alert['candidate_id'],key=alert['key'],rank=alert['rank'])
        directory=attempts[alert['key']]
        requests=list((directory/'admission').glob('item_*/request.json'))
        if len(requests)!=1:raise ValueError('Ambiguous first-stage request')
        record['first_request']=frozen(requests[0])
        match=by.get(alert['key'])
        if match:
            second=args.reviews/match['name']
            record.update(second_request=frozen(second/'request.json'),completion=frozen(second/'completion/completion.txt'),receipt=frozen(second/'completion/manifest.json'))
            record['cache_miss_reason']=compatible(read(requests[0]),read(second/'request.json'))
        else:record['cache_miss_reason']='no_exact_candidate_review'
        items.append(record)
    protocol=dict(version=VERSION,items=items,cases=[row['case'] for row in first['cases']],
        baseline=frozen(args.baseline/'summary.json'),review_experiment=frozen(args.reviews/'summary.json'),
        algorithm=frozen(Path(__file__)),gate_implementation=frozen(Path(compact_admission.__file__)),
        selection='Fixed first-stage outputs only. No candidate replacement after second-stage rejection.',
        cache_policy='Identical complete source payload, plus API documentation/type context; changed payload abstains.',
        retrospective=True,external_model_calls=0,new_native_executions=0,evaluation_labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(root/'prepared.json',protocol);write(root/'seal.json',frozen(root/'prepared.json'))
    return dict(trials=len(protocol['cases']),first_alerts=len(items),compatible_reviews=sum(not r['cache_miss_reason'] for r in items))


def run(args):
    root=args.input;verify(read(root/'seal.json'));p=read(root/'prepared.json')
    for key in ('baseline','review_experiment','algorithm','gate_implementation'):verify(p[key])
    rows=[];used_tokens=used_calls=0
    for item in p['items']:
        for key in ('first_request','second_request','completion','receipt'):
            if key in item:verify(item[key])
        if item['cache_miss_reason']:
            decision=dict(status='unknown',alarm_eligible=False,reason=item['cache_miss_reason'])
        else:
            request=read(item['second_request']['path']);receipt=read(item['receipt']['path'])
            if receipt['status']!='complete':decision=dict(status='unknown',alarm_eligible=False,reason='provider_response_incomplete')
            else:
                decision=compact_admission.decide(request,Path(item['completion']['path']).read_text(),finish_reason=receipt.get('finish_reason'))
            used_calls+=1;used_tokens+=receipt.get('usage',{}).get('total_tokens',0)
        row=dict(case=item['case'],candidate_id=item['candidate_id'],key=item['key'],decision=decision)
        rows.append(row);write(root/'cases'/item['case']/'decision.json',row)
    baseline=read(p['baseline']['path']);review=read(p['review_experiment']['path'])
    summary=dict(version=VERSION,denominator=len(p['cases']),decisions=rows,
        alerts=[r for r in rows if r['decision'].get('alarm_eligible')],
        compatible_cached_reviews=used_calls,compatible_cached_review_tokens=used_tokens,
        first_stage_calls=baseline['provider_calls'],first_stage_tokens=baseline['accounted_tokens'],
        entire_second_gate_experiment_cost=dict(calls=review.get('provider_calls'),tokens=review.get('accounted_tokens')),
        fresh_provider_calls=0,new_native_executions=0,retrospective=True,
        independent_audit_complete=False,completed_utc=datetime.now(timezone.utc).isoformat())
    write(root/'summary.json',summary)
    return {key:summary[key] for key in ('denominator','compatible_cached_reviews','compatible_cached_review_tokens','fresh_provider_calls')}|dict(alerts=len(summary['alerts']))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--baseline',type=Path);parser.add_argument('--reviews',type=Path)
    parser.add_argument('--output',type=Path);parser.add_argument('--input',type=Path)
    a=parser.parse_args();print(json.dumps(prepare(a) if a.stage=='prepare' else run(a)))
