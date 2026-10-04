from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts import run_contract_gap_generation_search as original
from scripts import run_atomic_contract_gap_generation_search as runner


def prepared(tmp_path):
    cases=[]
    for index in range(17):
        source=tmp_path/'sources'/str(index);repository=source/'repository';repository.mkdir(parents=True)
        code=('from api import double\n'+'\n'.join(f'def test_value_{i}():\n    assert double(3) == 6\n' for i in range(3))) if index<2 else 'x = 1\n'
        api='def double(n):\n    """Return twice n."""\n    return n*2\n'
        (repository/'test_value.py').write_text(code);(repository/'api.py').write_text(api)
        frontend=extract_frontend([Source('test_value.py',code,'python','repository'),Source('api.py',api,'python','repository')])
        runner.write(source/'corpus.json',to_emitter_corpus(frontend));runner.write(source/'frontend.json',frontend)
        runner.write(source/'case.json',dict(repository=str(repository)));runner.write(source/'selection.json',{})
        (source/'issue.md').write_text('double returns twice its input.')
        cases.append(dict(case=f'trial{index:02d}',source=str(source)))
    cohort=tmp_path/'cohort';runner.write(cohort/'prepared.json',dict(cases=cases))
    runner.write(cohort/'seal.json',runner.frozen(cohort/'prepared.json'))
    deadline=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    r18=tmp_path/'r18';original.prepare(SimpleNamespace(source_cohort=cohort,output=r18,deadline_utc=deadline))
    # Forbidden generation material is present, but not an input to R22.
    (r18/'cases/trial00/generation/decoded.json').write_text('PRIVATE_GENERATED_NOT_JSON')
    r22=tmp_path/'r22';result=runner.prepare(SimpleNamespace(source_cohort=r18,output=r22,deadline_utc=deadline))
    assert result['slots']==51 and result['requests']==6
    return SimpleNamespace(input=r22),runner.read(r22/'prepared.json')


def provider(calls, fault=None):
    def dispatch(request, output, *, root):
        generation=request['kind']==runner.relation.VERSION
        payload=json.loads(request['prompt']);slot=payload.get('generation_slot')
        calls.append((generation,slot))
        if generation:
            seed=payload['seeds'][0];code=seed['context']['original_test'].replace('double(3) == 6','double(4) == 8')
            if fault=='escape' and slot==1:code+='\ndef test_extra():\n    assert False'
            content=json.dumps(dict(tests=[dict(seed_alias=seed['seed_alias'],rewritten_test=code)]))
            if fault=='format' and slot==1:content='{"tests":'
            finish='length' if fault=='length' and slot==1 else 'stop'
        else:
            content=json.dumps(dict(basis='public contract',judgments={k:'supported' for k in request['check_ids']}));finish='stop'
        output.mkdir()
        runner.write(output/'request.json',dict(messages=[dict(role='system',content=request['system']),dict(role='user',content=request['prompt'])],max_tokens=request['max_tokens'],thinking=dict(type=request['thinking']),reasoning_effort=request['reasoning_effort'],model='fixture'))
        raw=dict(model='fixture',usage=dict(total_tokens=100),choices=[dict(message=dict(content=content),finish_reason=finish)])
        body=json.dumps(raw).encode();(output/'response.body').write_bytes(body)
        runner.write(output/'response.json',raw);(output/'completion.txt').write_text(content)
        runner.write(output/'manifest.json',dict(status='complete',external_model_calls=1,request_id=request['id'],request_sha256=original.admission.digest(output/'request.json'),response_sha256=hashlib.sha256(body).hexdigest(),model='fixture',response_model='fixture',finish_reason=finish,usage=dict(total_tokens=100)))
    return dispatch


def native_args(args):return SimpleNamespace(input=args.input/'native')


def test_prepare_uses_only_sealed_source_and_leaves_shared_modules_unchanged(tmp_path):
    before=(original.VERSION,original.relation,original.dispatch,original._generation_case_result)
    args,p=prepared(tmp_path)
    assert p['generation_policy']['max_calls']==45 and p['semantic_policy']['max_calls']==45
    assert len(p['cases'])==17 and all(len(c['slots'])==3 for c in p['cases'])
    assert p['cases'][0]['review_projection']==original.read(tmp_path/'r18/prepared.json')['cases'][0]['review_projection']
    assert not list(args.input.rglob('dispatch_claim.json'))
    assert before==(original.VERSION,original.relation,original.dispatch,original._generation_case_result)


def test_slot_round_robin_refusals_full_ledger_and_fresh_review(tmp_path,monkeypatch):
    args,p=prepared(tmp_path);calls=[];monkeypatch.setattr(runner,'dispatch',provider(calls,'escape'))
    generated=runner.generate(args)
    assert calls==[(True,1),(True,1),(True,2),(True,2),(True,3),(True,3)]
    assert generated['candidates']==4 and generated['generation_model_calls']==6
    summary=runner.read(args.input/'generation_summary.json')
    assert len(summary['results'])==17 and summary['measured_tokens']==600
    ledger=runner.read(args.input/'cases/trial00/generation/decoded.json')['slot_ledger']
    assert ledger[0]['disposition']=='structurally_rejected'
    assert [row['slot'] for row in ledger]==[1,2,3]
    assert [e['rank'] for e in runner.read(args.input/'native/prepared.json')['cases'][0]['candidates']]==[2,3]
    assert runner.generate(args)==generated and len(calls)==6
    assert runner.review_all(native_args(args))['admitted']==4
    assert len(calls)==10 and all(not c[0] for c in calls[6:])
    assert runner.review_all(native_args(args))['admitted']==4 and len(calls)==10


@pytest.mark.parametrize('fault',['length','format','interrupted'])
def test_unknowns_are_accounted_preserve_slot_and_never_retry(tmp_path,monkeypatch,fault):
    args,p=prepared(tmp_path);calls=[]
    if fault=='interrupted':
        slot=p['cases'][0]['slots'][0];req=runner.read(slot['request']['path'])
        runner.write(args.input/'cases/trial00/generation/slot_0001/dispatch_claim.json',dict(request=slot['request'],reserved_calls=1,reserved_tokens=runner._reservation(req)))
    monkeypatch.setattr(runner,'dispatch',provider(calls,fault))
    runner.generate(args);count=len(calls);runner.generate(args);assert len(calls)==count
    summary=runner.read(args.input/'generation_summary.json')
    assert summary['reserved_calls']==int(fault=='interrupted')
    ledger=runner.read(args.input/'cases/trial00/generation/decoded.json')['slot_ledger']
    assert ledger[0]['status']=='unknown' and ledger[1]['slot']==2
    if fault in {'length','format'}:
        assert ledger[0]['disposition']==('length' if fault=='length' else 'format_unknown')


def test_first_failure_plus_repeat_stops_with_complete_generation_provenance(tmp_path,monkeypatch):
    args,p=prepared(tmp_path);calls=[];native=[];monkeypatch.setattr(runner,'dispatch',provider(calls))
    runner.generate(args);runner.review_all(native_args(args))
    def run(candidate,source,corpus,target,protocol):
        native.append((Path(source).name,candidate['order'][0]))
        outcome=dict(transport=dict(status='matched'),native=dict(controls=dict(status='all_source_controls_passed'),controlled_failure=True))
        runner.write(target/'native_outcome.json',dict(fixture=True));runner.write(target/'outcome.json',outcome)
        return outcome
    monkeypatch.setattr(runner,'one_run',run)
    result=runner.run(native_args(args))
    assert native==[('0',1),('0',1),('1',1),('1',1)]
    assert result['generation_model_calls']==6 and result['semantic_review_model_calls']==6
    assert result['detector_alerts']==2 and result['native_executions']==4
    assert runner.run(native_args(args))['detector_alerts']==2 and len(native)==4


def test_changed_raw_generation_or_aggregate_cannot_authorize_review(tmp_path,monkeypatch):
    args,p=prepared(tmp_path);calls=[];monkeypatch.setattr(runner,'dispatch',provider(calls));runner.generate(args)
    path=args.input/'cases/trial00/generation/slot_0002/completion/completion.txt'
    path.write_text('changed raw proposal')
    with pytest.raises(ValueError):runner.review_all(native_args(args))
    assert len(calls)==6


def test_budget_withheld_records_every_slot_without_dispatch(tmp_path,monkeypatch):
    args,p=prepared(tmp_path);calls=[];monkeypatch.setattr(runner,'dispatch',provider(calls))
    monkeypatch.setattr(runner,'_reservation',lambda request:1000001)
    generated=runner.generate(args)
    assert generated['candidates']==0 and calls==[]
    ledger=runner.read(args.input/'cases/trial00/generation/decoded.json')['slot_ledger']
    assert [r['disposition'] for r in ledger]==['generation_budget']*3
    absent=runner.read(args.input/'cases/trial02/generation/decoded.json')['slot_ledger']
    assert [r['disposition'] for r in absent]==['no_anchor']*3
    assert runner.read(args.input/'generation_summary.json')['provider_calls']==0
