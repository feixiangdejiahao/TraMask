"""Run a finite portfolio with masked oracle derivation and complete review.

Selection responses come from the recorded source-only ranking component.
Every oracle answer is fresh. A native failure is reviewed without disclosing
its result to the provider. Stop at the first supported failure per trial.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import compact_admission,expected_slots,source_contract_evidence
from relation_search.checkpoint import read,digest
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import Budget,execute,write,frozen,verify


VERSION='finite-portfolio-masked-oracle-search.v1'


def normalized_ranking(request,content,finish_reason):
    """First occurrence wins in a complete finite ranking; unknown aliases fail."""
    if finish_reason!='stop':return dict(selected=[],error='incomplete_provider_response')
    try:value=json.loads(content)
    except (ValueError,TypeError):return dict(selected=[],error='invalid_json')
    if not isinstance(value,dict) or set(value)!={'ranking'} or not isinstance(value['ranking'],list):
        return dict(selected=[],error='invalid_ranking_schema')
    seen=set();selected=[];duplicates=0
    for alias in value['ranking']:
        if not isinstance(alias,str) or alias not in request['aliases']:
            return dict(selected=[],error='unknown_candidate_alias')
        if alias in seen:
            duplicates+=1;continue
        seen.add(alias)
        if len(selected)<request['budget']:selected.append(request['aliases'][alias])
    return dict(selected=selected,duplicate_aliases_removed=duplicates,
                returned_ranking_length=len(value['ranking']))


def prepare(args):
    root=args.output;root.mkdir(parents=True,exist_ok=False)
    verify(read(args.selection/'seal.json'))
    selection=read(args.selection/'prepared.json');cases=[]
    for entry in selection['cases']:
        directory=args.selection/entry['case'];request=read(directory/'request.json')
        verify(entry['request']);verify(entry['catalog'])
        receipt=read(directory/'completion/manifest.json')
        if receipt['status']!='complete':result=dict(selected=[],error='provider_error')
        else:result=normalized_ranking(request,(directory/'completion/completion.txt').read_text(),receipt.get('finish_reason'))
        for source in entry['source_inputs'].values():verify(source)
        write(root/'cases'/entry['case']/'selection.json',result)
        cases.append(dict(case=entry['case'],source=entry['source'],catalog=entry['catalog'],
            source_inputs=entry['source_inputs'],selected=result['selected'],
            ranking_request=frozen(directory/'request.json'),
            ranking_receipt=frozen(directory/'completion/manifest.json'),
            ranking_response=frozen(directory/'completion/completion.txt'),
            selection=frozen(root/'cases'/entry['case']/'selection.json')))
    for module in (compact_admission,expected_slots,source_contract_evidence):admission._preload_local_imports(module)
    protocol=dict(version=VERSION,cases=cases,algorithm=admission._loaded_sources(),
        selection_component=frozen(args.selection/'prepared.json'),
        selection_summary=frozen(args.selection/'summary.json'),
        selection_normalization='first_occurrence_of_known_alias_in_complete_response',
        max_model_calls=args.max_model_calls,max_total_tokens=args.max_total_tokens,
        max_prompt_bytes=96000,derivation_output_tokens=4096,review_output_tokens=4096,
        deadline_utc=args.deadline_utc,timeout=args.timeout,
        order='portfolio_rank_then_case_round_robin',source_enrichment=True,
        api_documentation_context=True,gate='compact',
        no_slot_policy='review_unchanged_program',
        derivation_unknown_policy='no_execution_or_alert',
        native_pass_policy='no_whole_test_review_or_alert',
        stop='first_supported_controlled_native_failure_per_trial',
        native_feedback_sent_to_provider=False,evaluator_truth_used=False,
        provider_selection_answers_reused=True,provider_oracle_answers_reused=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(root/'prepared.json',protocol);write(root/'seal.json',frozen(root/'prepared.json'))
    return dict(cases=len(cases),programs=sum(len(c['selected']) for c in cases))


def context_review(corpus,frontend,candidate,issue,protocol):
    result=compact_admission.prepare(corpus,frontend,candidate,issue,
        max_prompt_bytes=protocol['max_prompt_bytes'],max_output_tokens=protocol['review_output_tokens'])
    request=result.get('request')
    if request is None:return result
    evidence=source_contract_evidence.collect(corpus,result['analysis'])
    payload=json.loads(request['prompt'])
    if evidence['records']:payload['api_contract_context']=evidence
    request['prompt']=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    request['prompt_bytes']=len(request['system'].encode())+len(request['prompt'].encode())
    fields={k:request[k] for k in ('system','prompt','thinking','max_tokens')}
    request['id']=request['query_sha256']=compact_admission._hash(fields)
    result['api_contract_context']=evidence
    if request['prompt_bytes']>protocol['max_prompt_bytes']:
        result.update(status='unknown_prompt_budget',request=None)
    return result


def run(args):
    root=args.input
    with (root/'.run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verify(read(root/'seal.json'));protocol=read(root/'prepared.json')
        admission.verify_seal(protocol['algorithm']);budget=Budget(root,protocol)
        cache={};results={entry['case']:dict(case=entry['case'],attempts=[],alert=None) for entry in protocol['cases']}
        for rank in range(max((len(c['selected']) for c in protocol['cases']),default=0)):
            for entry in protocol['cases']:
                case=entry['case'];result=results[case]
                if result['alert'] or rank>=len(entry['selected']):continue
                directory=root/'cases'/case/f'candidate_{rank+1:04d}'
                if (directory/'outcome.json').exists():
                    outcome=read(directory/'outcome.json');result['attempts'].append(outcome)
                    result['alert']=outcome.get('alert');continue
                if not budget.enough_time(protocol['timeout']+300):continue
                if budget.totals()['calls']>=protocol['max_model_calls']:continue
                if case not in cache:
                    for source in entry['source_inputs'].values():verify(source)
                    verify(entry['catalog']);catalog={c['id']:c for c in read(entry['catalog']['path'])}
                    path=Path(entry['source']);corpus=read(path/'corpus.json');frontend=read(path/'frontend.json')
                    corpus,receipt=admission._enrich(corpus,frontend,catalog,str(path/'corpus.json'),root/'cases'/case,0)
                    cache[case]=(corpus,frontend,catalog,(path/'issue.md').read_text())
                corpus,frontend,catalog,issue=cache[case]
                candidate=catalog[entry['selected'][rank]]
                # This source-only context also supplies complete fixed checks
                # to the later reviewer. It contains no native outcome.
                context=context_review(corpus,frontend,candidate,issue,protocol)
                context_request=context.pop('request');write(directory/'source_analysis.json',context)
                context_wire=json.loads(context_request['prompt']) if context_request else {}
                proposal=expected_slots.prepare(corpus,frontend,candidate,issue,context=context_wire,
                    max_prompt_bytes=protocol['max_prompt_bytes'],max_output_tokens=protocol['derivation_output_tokens'])
                request=proposal.pop('request');write(directory/'derivation/analysis.json',proposal)
                chosen=None;decision=None
                if request:
                    content,receipt=budget.call(request,directory/'derivation')
                    decision=(expected_slots.validate(request,content,corpus,finish_reason=receipt.get('finish_reason'))
                              if content is not None else dict(status='unknown',candidate=None,reason=receipt['status']))
                    chosen=decision.pop('candidate');write(directory/'derivation/decision.json',decision)
                elif proposal['status'] in {'unknown_no_assertions','unknown_no_typed_slots'}:
                    chosen=candidate
                outcome=dict(rank=rank+1,candidate_id=candidate['id'],derivation=decision or proposal,alert=None)
                if chosen is not None:
                    write(directory/'selected_program.json',chosen)
                    native=execute(chosen,Path(entry['source']),corpus,directory/'native',protocol)
                    outcome['native']={k:native[k] for k in ('candidate_id','controlled_failure','runs')}
                    if native['controlled_failure']:
                        review=context_review(corpus,frontend,chosen,issue,protocol)
                        request=review.pop('request');write(directory/'review/analysis.json',review)
                        if request:
                            content,receipt=budget.call(request,directory/'review')
                            decision=(compact_admission.decide(request,content,finish_reason=receipt.get('finish_reason'))
                                      if content is not None else dict(status='unknown',alarm_eligible=False,reason=receipt['status']))
                        else:decision=dict(status=review['status'],alarm_eligible=False)
                        write(directory/'review/decision.json',decision);outcome['review']=decision['status']
                        if decision.get('alarm_eligible'):
                            outcome['alert']=dict(case=case,rank=rank+1,candidate_id=chosen['id'],
                                program=frozen(directory/'selected_program.json'),native=frozen(directory/'native/native_outcome.json'),
                                validity='model_hypothesis_pending_independent_audit')
                write(directory/'outcome.json',outcome);result['attempts'].append(outcome);result['alert']=outcome.get('alert')
                print(json.dumps(dict(case=case,rank=rank+1,alert=bool(result['alert']),**budget.totals())),flush=True)
        admission.verify_seal(protocol['algorithm'])
        for result in results.values():write(root/'cases'/result['case']/'result.json',result)
        selection=read(protocol['selection_summary']['path'])
        summary=dict(version=VERSION,denominator=len(results),cases=list(results.values()),
            alerts=[row['alert'] for row in results.values() if row['alert']],**budget.totals(),
            selection_costs=dict(provider_calls=selection['provider_calls'],accounted_tokens=selection['accounted_tokens']),
            independent_audit_complete=False,completed_utc=datetime.now(timezone.utc).isoformat())
        write(root/'summary.json',summary)
        return {k:v for k,v in summary.items() if k not in {'cases','alerts'}}|dict(reported_alerts=len(summary['alerts']))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--selection',type=Path);parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--max-model-calls',type=int,default=256);parser.add_argument('--max-total-tokens',type=int,default=4000000)
    parser.add_argument('--timeout',type=int,default=180);parser.add_argument('--deadline-utc',default='2026-10-04T01:51:21Z')
    args=parser.parse_args();print(json.dumps(prepare(args) if args.stage=='prepare' else run(args)))
