import copy
import json
from pathlib import Path

import pytest

from scripts import archived_absence_null_validation as check
from scripts import run_archived_component_chain as chain


def put(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    return chain.frozen(path)


class DataVerifier:
    def __init__(self): self.dependencies=[]
    def receipt(self, receipt, role):
        assert role=='data'
        path=Path(receipt['path']).resolve()
        if chain.frozen(path)!=receipt: raise ValueError('Changed data artifact')
        return path
    def receipts(self,value):
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value: self.receipt(value,'data')
            for x in value.values(): self.receipts(x)
        if isinstance(value,list):
            for x in value: self.receipts(x)
    def source_inventory(self,p): return {c['case']:{} for c in p['cases']}


@pytest.fixture
def semantic_fixture(tmp_path):
    policy=dict(method=check.source.review.VERSION,max_calls=64,max_total_tokens=1000000,
        max_output_tokens=16384,thinking='enabled',reasoning_effort='high',
        ordering='source candidate ranks round robin over sorted trial names',
        native_outcomes_sent=False,evaluation_labels_sent=False)
    cases=[dict(case=n,candidates=[]) for n in ('a','b')]
    records=[]
    for rank in (1,2):
        for case in cases:
            directory=tmp_path/'cases'/case['case']/f'candidate_{rank:04d}'/'review'
            program=put(directory.parent/'program.json',dict(id=case['case']+str(rank)))
            analysis=put(directory/'analysis.json',dict(status='prepared'))
            request=dict(system='Check this test',prompt='{}',max_tokens=16384,thinking='enabled',reasoning_effort='high',
                kind=check.source.review.VERSION,codec_guard=dict(allow_prior_gate=True),check_ids=['P','Q0'],coverage={})
            request['id']=check.source.admission._request_identity(request)
            request_ref=put(directory/'request.json',request)
            entry=dict(rank=rank,program=program,analysis=analysis,request=request_ref)
            case['candidates'].append(entry)
            reserve=check.source._reservation(request)
            put(directory/'dispatch_claim.json',dict(request=request_ref,reserved_tokens=reserve,reserved_calls=1))
            text=json.dumps(dict(basis='Explicit fixture contract',judgments=dict(P='supported',Q0='supported')))
            wire=dict(messages=[dict(role='system',content=request['system']),dict(role='user',content=request['prompt'])],
                max_tokens=request['max_tokens'],thinking=dict(type='enabled'),reasoning_effort='high',model='fixture-model')
            wire_ref=put(directory/'completion/request.json',wire)
            raw=dict(choices=[dict(message=dict(content=text),finish_reason='stop')],usage=dict(total_tokens=20),model='fixture-model')
            body=json.dumps(raw).encode();(directory/'completion/response.body').write_bytes(body)
            put(directory/'completion/response.json',raw);(directory/'completion/completion.txt').write_text(text)
            manifest=dict(request_id=request['id'],request_sha256=wire_ref['sha256'],response_sha256=check.sha(body),model='fixture-model',
                status='complete',external_model_calls=1,finish_reason='stop',usage=raw['usage'],response_model=raw['model'])
            put(directory/'completion/manifest.json',manifest)
            decision=check.source.review.decide(request,text)
            row=dict(case=case['case'],rank=rank,program=program,decision=put(directory/'decision.json',decision),
                status=decision['status'],admitted=True,**check.source._cost(manifest,reserve))
            row['artifacts']=check.source._artifacts(directory)
            put(directory/'result.json',row);records.append(row)
    protocol=dict(version=check.VERSION,cases=cases,trial_denominator=2,semantic_policy=policy,
        ordering='retrieval_rank, source path, value start byte',max_candidates_per_trial=16,
        stop='First controlled failure, then one repeat; stop even if the repeat does not confirm.')
    prepared=put(tmp_path/'prepared.json',protocol)
    value=dict(version=check.VERSION,stage='complete',prepared=prepared,trial_denominator=2,native_executions=0,
        results=records,result_receipts=[chain.frozen(tmp_path/'cases'/r['case']/f"candidate_{r['rank']:04d}"/'review/result.json') for r in records],
        admitted=4,**check.source._totals(records))
    summary=dict(semantic_summary=put(tmp_path/'semantic_summary.json',value))
    return tmp_path,protocol,prepared,value,summary


def verify_fixture(fixture):
    root,p,prepared,sem,summary=fixture
    return check.semantic(DataVerifier(),p,summary,root,prepared)


def reseal(fixture, index=0):
    root,p,prepared,sem,summary=fixture
    row=sem['results'][index];directory=root/'cases'/row['case']/f"candidate_{row['rank']:04d}"/'review'
    row['artifacts']=check.source._artifacts(directory)
    sem['result_receipts'][index]=put(directory/'result.json',row)
    summary['semantic_summary']=put(root/'semantic_summary.json',sem)


def test_complete_semantic_trace_reuses_static_validator_without_dispatch(semantic_fixture,monkeypatch):
    monkeypatch.setattr(check.source,'dispatch',lambda *a,**k:pytest.fail('provider called'))
    monkeypatch.setattr(check.source,'one_run',lambda *a,**k:pytest.fail('native called'))
    assert len(verify_fixture(semantic_fixture)['admitted'])==4


def test_semantic_order_is_not_just_set_equality(semantic_fixture):
    root,p,prep,sem,summary=semantic_fixture
    sem['results'].reverse();sem['result_receipts'].reverse()
    summary['semantic_summary']=put(root/'semantic_summary.json',sem)
    with pytest.raises(ValueError,match='decision order'):verify_fixture(semantic_fixture)


@pytest.mark.parametrize('change', ['completion','parsed_response','wire','decision','cost','claim'])
def test_resigned_semantic_artifacts_still_must_agree(semantic_fixture,change):
    root,p,prep,sem,summary=semantic_fixture
    d=root/'cases/a/candidate_0001/review'
    if change=='completion': (d/'completion/completion.txt').write_text('changed')
    elif change=='parsed_response':
        raw=check.read(d/'completion/response.json');raw['model']='other';put(d/'completion/response.json',raw)
    elif change=='wire':
        wire=check.read(d/'completion/request.json');wire['messages'][1]['content']='altered';ref=put(d/'completion/request.json',wire)
        m=check.read(d/'completion/manifest.json');m['request_sha256']=ref['sha256'];put(d/'completion/manifest.json',m)
    elif change=='decision':
        decision=check.read(d/'decision.json');decision['basis']='not from provider';sem['results'][0]['decision']=put(d/'decision.json',decision)
    elif change=='cost':sem['results'][0]['measured_tokens']+=1
    elif change=='claim':
        claim=check.read(d/'dispatch_claim.json');claim['reserved_tokens']+=1;put(d/'dispatch_claim.json',claim)
    reseal(semantic_fixture)
    with pytest.raises(ValueError): verify_fixture(semantic_fixture)


def test_budget_is_checked_at_each_dispatch(semantic_fixture):
    semantic_fixture[1]['semantic_policy']['max_calls']=1
    with pytest.raises(ValueError,match='exceeded frozen budget'):verify_fixture(semantic_fixture)


def test_native_checkpoint_allows_only_declared_source_symlinks(tmp_path):
    original=put(tmp_path/'original.json',dict(data=1));directory=tmp_path/'prepared';directory.mkdir()
    (directory/'corpus.json').symlink_to(original['path'])
    put(directory/'checkpoint.json',dict(files_sha256={'corpus.json':original['sha256']}))
    check.checkpoint(DataVerifier(),directory,input_receipts={'corpus.json':original})
    with pytest.raises(ValueError,match='unknown checkpoint edge'):check.checkpoint(DataVerifier(),directory)
    Path(original['path']).write_text('tampered')
    with pytest.raises(ValueError,match='Changed data'):check.checkpoint(DataVerifier(),directory,input_receipts={'corpus.json':original})


def test_validator_algorithm_covers_new_module_and_reused_static_helpers():
    paths={r['path'] for r in chain.verification_algorithm().values()}
    assert str(Path(check.__file__).resolve()) in paths
    assert str(Path(check.source.__file__).resolve()) in paths
    assert chain.VERSION.endswith('.v3')
    assert {'archived-complete-component-chain.v1','archived-complete-component-chain.v2'}<=chain.ARCHIVES


@pytest.fixture
def native_fixture(tmp_path,monkeypatch):
    entries=[dict(rank=n,program=put(tmp_path/f'program{n}.json',dict(order=[n])),order=[n]) for n in (1,2)]
    case=dict(case='a',candidates=entries,status='source_hypotheses')
    protocol=dict(cases=[case],trial_denominator=1,max_native_executions=5)
    semantics=dict(admitted={('a',1),('a',2)},decisions={('a',1):{},('a',2):{}},provider_calls=2)
    row=dict(case='a',attempts=[],alert=None,stop_reason='candidate_budget_exhausted')
    for e in entries:
        d=tmp_path/'cases/a'/f"candidate_{e['rank']:04d}"/'initial'
        out=dict(transport=dict(status='matched'),native=dict(controls=dict(status='all_source_controls_passed'),controlled_failure=False))
        receipt=put(d/'outcome.json',out);put(d/'native/native_outcome.json',out['native'])
        row['attempts'].append(dict(rank=e['rank'],program=e['program'],initial=out,initial_receipt=receipt))
    summary=dict(results=[row],result_receipts=[put(tmp_path/'cases/a/result.json',row)],trial_denominator=1,native_executions=2,external_model_calls=2,detector_alerts=0)
    monkeypatch.setattr(check,'projection',lambda *a:None)
    monkeypatch.setattr(check,'source_review',lambda *a:None)
    monkeypatch.setattr(check,'semantic',lambda *a:semantics)
    monkeypatch.setattr(check.source,'_read_sealed',lambda *a:summary)
    monkeypatch.setattr(check.source,'_verified_case_result',lambda *a:row)
    monkeypatch.setattr(check,'native_phase',lambda *a:1)
    return tmp_path,protocol,summary,row,semantics


def reseal_native(f):
    root,p,summary,row,sem=f;summary['result_receipts']=[put(root/'cases/a/result.json',row)]


def test_native_admitted_prefix_complete(native_fixture):
    root,p,s,_,_=native_fixture
    assert check.validate(DataVerifier(),p,s,{},root)['summary']['native_executions']==2


@pytest.mark.parametrize('mutation',['reorder','unadmitted','continue_after_fail','fake_alert','drop_result'])
def test_native_trace_cannot_skip_reorder_or_bypass_semantics(native_fixture,mutation):
    root,p,s,row,sem=native_fixture
    if mutation=='reorder':row['attempts'].reverse()
    elif mutation=='unadmitted':sem['admitted'].remove(('a',1))
    elif mutation=='continue_after_fail':row['attempts'][0]['initial']['native']['controlled_failure']=True
    elif mutation=='fake_alert':row['alert']={'unsupported':'alert'}
    elif mutation=='drop_result':s['results']=[]
    reseal_native(native_fixture)
    with pytest.raises(ValueError):check.validate(DataVerifier(),p,s,{},root)


def test_confirmation_cannot_reuse_initial_runs_receipt(tmp_path,monkeypatch):
    initial=tmp_path/'initial';confirmation=tmp_path/'confirmation'
    corpus=put(tmp_path/'corpus.json',dict(language='python'))
    program=put(tmp_path/'program.json',dict(id='candidate'))
    native=dict(runs=put(initial/'native/executed/runs.json',[]))
    out=dict(native=native,transport={})
    receipt=put(confirmation/'outcome.json',out)
    put(confirmation/'native/native_outcome.json',native)
    monkeypatch.setattr(check,'checkpoint',lambda *a,**k:None)
    with pytest.raises(ValueError,match='receipt path differs'):
        check.native_phase(DataVerifier(),dict(inputs={'corpus.json':corpus}),dict(program=program),
            'confirmation',out,receipt,confirmation)


def test_prompt_is_reconstructed_from_source_projection(tmp_path,monkeypatch):
    corpus=put(tmp_path/'corpus.json',{});frontend=put(tmp_path/'frontend.json',{})
    issue=tmp_path/'issue.md';issue.write_text('public contract')
    projection=put(tmp_path/'projection.json',dict(corpus=corpus,frontend=frontend))
    candidate=put(tmp_path/'program.json',{})
    analysis=put(tmp_path/'analysis.json',dict(status='unknown_static'))
    case=dict(review_projection=projection,inputs={'issue.md':chain.frozen(issue)},
        candidates=[dict(program=candidate,analysis=analysis,request=None)])
    policy=dict(max_prompt_bytes=96000,max_output_tokens=16384)
    monkeypatch.setattr(check.source.review,'prepare',lambda *a,**k:dict(status='unknown_static',request=None))
    check.source_review(DataVerifier(),dict(semantic_policy=policy),case)
    put(tmp_path/'analysis.json',dict(status='injected_history'))
    with pytest.raises(ValueError,match='analysis differs'):
        check.source_review(DataVerifier(),dict(semantic_policy=policy),case)


def test_historical_sources_cannot_enter_review_projection(tmp_path):
    code='def test_example():\n    assert True\n'
    original=put(tmp_path/'original.json',dict(sources={'test_x.py':dict(code=code,origin='repository')},tests={}))
    metadata=put(tmp_path/'case.json',dict(repository=str(tmp_path/'repository')))
    hashes={'test_x.py':check.sha(code.encode())}
    context=put(tmp_path/'context.json',dict(case_metadata=metadata,repository=str(tmp_path/'repository'),
        original_source_sha256=hashes,added_sources={}))
    projected=put(tmp_path/'projected.json',dict(sources={'test_x.py':dict(code=code,origin='trajectory')},tests={}))
    inputs={'corpus.json':original,'frontend.json':original,'case.json':metadata}
    projection=put(tmp_path/'projection.json',dict(version='repository-only-review-projection.v1',
        original_inputs={k:inputs[k] for k in ('corpus.json','frontend.json')},source_sha256=hashes,
        excluded_source_count=0,source_context=context,enriched_source_sha256=hashes,corpus=projected,frontend=projected))
    with pytest.raises(ValueError,match='historical source entered review'):
        check.projection(DataVerifier(),dict(inputs=inputs,candidates=[{}],review_projection=projection,source_context=context))
