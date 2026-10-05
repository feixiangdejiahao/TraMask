from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_contract_gap_generation_search as original
from scripts import run_omitted_anchor_generation_search as runner
from test_omitted_anchor_proposals import fixture


def prepared(tmp_path):
    engine=runner.engine();cases=[];corpus,frontend,issue,inherited=fixture()
    for index in range(17):
        source=tmp_path/'sources'/str(index);repository=source/'repository';repository.mkdir(parents=True)
        c,f=(corpus,frontend) if index<2 else (dict(language='python',sources={},tests={}),dict(language='python',sources={},tests=[]))
        # Re-extract an ordinary empty repository for the no-slot denominator rows.
        if index>=2:
            from anchor_retrieval.syntax import Source
            from relational_gap.frontend import extract_frontend,to_emitter_corpus
            f=extract_frontend([Source('empty.py','x = 1\n','python','repository')]);c=to_emitter_corpus(f)
        for name,row in c['sources'].items():(repository/name).write_text(row['code'])
        engine['write'](source/'corpus.json',c);engine['write'](source/'frontend.json',f)
        engine['write'](source/'case.json',dict(repository=str(repository)));engine['write'](source/'selection.json',{})
        (source/'issue.md').write_text(issue);cases.append(dict(case=f'trial{index:02d}',source=str(source)))
    cohort=tmp_path/'cohort';engine['write'](cohort/'prepared.json',dict(cases=cases));engine['write'](cohort/'seal.json',engine['frozen'](cohort/'prepared.json'))
    deadline=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat();r18=tmp_path/'r18'
    original.prepare(SimpleNamespace(source_cohort=cohort,output=r18,deadline_utc=deadline))
    protocol=engine['read'](r18/'prepared.json')
    for case in protocol['cases'][:2]:
        c,f=original._context(case)
        p=runner.relation.core.prepare(c,f,issue,max_prompt_bytes=inherited['prompt_bytes'])
        assert len(p['seeds'])==1 and len(p['omitted'])==3
        path=Path(case['generation']['path']);path.write_text(json.dumps(p))
        req=Path(case['generation_request']['path']);req.write_text(json.dumps(p['request']))
        case['generation']=engine['frozen'](path);case['generation_request']=engine['frozen'](req)
        (path.parent/'decoded.json').write_text('FORBIDDEN_OLD_GENERATION_NOT_JSON')
    (r18/'prepared.json').write_text(json.dumps(protocol));(r18/'seal.json').write_text(json.dumps(engine['frozen'](r18/'prepared.json')))
    output=tmp_path/'r33';result=engine['prepare'](SimpleNamespace(source_cohort=r18,output=output,deadline_utc=deadline))
    assert result['requests']==6 and result['slots']==51
    return engine,SimpleNamespace(input=output),engine['read'](output/'prepared.json')


def provider(calls,fault=None):
    def dispatch(request,output,*,root):
        generation=request['kind']==runner.relation.VERSION;payload=json.loads(request['prompt']);slot=payload.get('generation_slot')
        calls.append((generation,slot,request['reasoning_effort']))
        if generation:
            seed=payload['seeds'][0];code=seed['context']['original_test'].replace('double(3) == 6','double(4) == 8')
            content=json.dumps(dict(tests=[dict(seed_alias=seed['seed_alias'],rewritten_test=code)]));finish='length' if fault=='length' and slot==1 else 'stop'
        else:content=json.dumps(dict(basis='public contract',judgments={k:'supported' for k in request['check_ids']}));finish='stop'
        output.mkdir()
        original.write(output/'request.json',dict(messages=[dict(role='system',content=request['system']),dict(role='user',content=request['prompt'])],max_tokens=request['max_tokens'],thinking=dict(type=request['thinking']),reasoning_effort=request['reasoning_effort'],model='fixture'))
        raw=dict(model='fixture',usage=dict(total_tokens=100),choices=[dict(message=dict(content=content),finish_reason=finish)])
        body=json.dumps(raw).encode();(output/'response.body').write_bytes(body);original.write(output/'response.json',raw);(output/'completion.txt').write_text(content)
        original.write(output/'manifest.json',dict(status='complete',external_model_calls=1,request_id=request['id'],request_sha256=original.admission.digest(output/'request.json'),response_sha256=hashlib.sha256(body).hexdigest(),model='fixture',response_model='fixture',finish_reason=finish,usage=dict(total_tokens=100)))
    return dispatch


def test_prepare_freezes_complete_origins_slots_low_budget_without_mutating_shared_modules(tmp_path):
    before=(original.VERSION,original.relation,original.dispatch)
    e,args,p=prepared(tmp_path)
    assert p['generation_policy']['max_calls']==12 and p['semantic_policy']['max_calls']==12
    assert p['generation_policy']['reasoning_effort']=='low' and p['semantic_policy']['reasoning_effort']=='high'
    assert len(p['cases'])==17 and all(len(c['slots'])==3 for c in p['cases'])
    for case in p['cases']:e['_verify_case_inputs'](case)
    assert before==(original.VERSION,original.relation,original.dispatch)
    assert not list(args.input.rglob('dispatch_claim.json'))


def test_raw_resume_then_fresh_gate_preserves_omitted_slot_order_and_provenance(tmp_path):
    e,args,p=prepared(tmp_path);calls=[];e['dispatch']=provider(calls,'length')
    generated=e['generate'](args)
    assert calls==[(True,1,'low')]*2+[(True,2,'low')]*2+[(True,3,'low')]*2
    assert generated['candidates']==4 and generated['generation_model_calls']==6
    assert e['generate'](args)==generated and len(calls)==6
    nativeargs=SimpleNamespace(input=args.input/'native')
    assert e['review_all'](nativeargs)['admitted']==4
    assert calls[6:]==[(False,None,'high')]*4
    assert e['review_all'](nativeargs)['admitted']==4 and len(calls)==10
    native=e['read'](nativeargs.input/'prepared.json')
    assert len(native['cases'])==17
    for case in native['cases'][:2]:
        assert [x['rank'] for x in case['candidates']]==[2,3]
        for row in case['candidates']:
            candidate=e['read'](row['program']['path'])
            assert candidate['source_provenance']['seed']==candidate['base_test_id']
    ledger=e['read'](args.input/'cases/trial00/generation/decoded.json')['slot_ledger']
    assert ledger[0]['disposition']=='length'


def test_native_uses_admitted_fixed_order_and_repeat_without_new_generation(tmp_path):
    e,args,p=prepared(tmp_path);calls=[];e['dispatch']=provider(calls);e['generate'](args)
    nativeargs=SimpleNamespace(input=args.input/'native');e['review_all'](nativeargs);runs=[]
    def one_run(candidate,source,corpus,target,protocol):
        runs.append((Path(source).name,candidate['order'][0]));assert candidate['source_provenance']
        outcome=dict(transport=dict(status='matched'),native=dict(controls=dict(status='all_source_controls_passed'),controlled_failure=True))
        e['write'](target/'native_outcome.json',dict(fixture=True));e['write'](target/'outcome.json',outcome);return outcome
    e['one_run']=one_run
    result=e['run'](nativeargs)
    assert runs==[('0',1),('0',1),('1',1),('1',1)]
    assert result['detector_alerts']==2 and result['native_executions']==4
    assert result['generation_model_calls']==6 and result['semantic_review_model_calls']==6
    assert e['run'](nativeargs)['detector_alerts']==2 and len(runs)==4


@pytest.mark.parametrize('target',['recovery','raw','summary'])
def test_tampered_recovery_or_completed_raw_summary_rejects_resume(tmp_path,target):
    e,args,p=prepared(tmp_path);calls=[];e['dispatch']=provider(calls)
    if target=='recovery':path=Path(p['cases'][0]['recovered_source_preparation']['path'])
    else:
        e['generate'](args)
        path=args.input/('cases/trial00/generation/slot_0001/completion/completion.txt' if target=='raw' else 'generation_summary.json')
    path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError):e['generate'](args)
    assert len(calls)==(0 if target=='recovery' else 6)


def test_budget_withheld_slots_are_not_replaced_by_visible_anchors(tmp_path):
    e,args,p=prepared(tmp_path);calls=[];e['dispatch']=provider(calls);e['_reservation']=lambda request:1000001
    result=e['generate'](args);assert result['candidates']==0 and calls==[]
    ledger=e['read'](args.input/'cases/trial00/generation/decoded.json')['slot_ledger']
    assert [row['disposition'] for row in ledger]==['generation_budget']*3
    assert len(e['read'](args.input/'generation_summary.json')['results'])==17
