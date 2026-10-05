from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts import run_contract_gap_generation_search as original
from scripts import run_protocol_text_refinement_search as runner


def prepared(tmp_path):
    cases=[]
    for index in range(17):
        source=tmp_path/'sources'/str(index);repository=source/'repository';repository.mkdir(parents=True)
        code=('import pytest\nfrom wire import Reader\n@pytest.fixture\ndef parser():\n    return Reader()\n'
            'def test_text(parser):\n    [event] = parser.feed("\\x1b[97;2:2;65u")\n'
            '    assert event.character == "A"\n    assert event.phase == "repeat"\n') if index<2 else 'x = 1\n'
        api='class Reader:\n    def feed(self,data):\n        """Decode Kitty keyboard protocol CSI into key events."""\n        return []\n'
        (repository/'test_wire.py').write_text(code);(repository/'wire.py').write_text(api)
        frontend=extract_frontend([Source('test_wire.py',code,'python','repository'),Source('wire.py',api,'python','repository')])
        for name,value in [('corpus',to_emitter_corpus(frontend)),('frontend',frontend),('case',dict(repository=str(repository))),('selection',{})]:runner.write(source/(name+'.json'),value)
        (source/'issue.md').write_text('Support the Kitty keyboard protocol and preserve phase metadata.')
        cases.append(dict(case=f'trial{index:02d}',source=str(source)))
    cohort=tmp_path/'cohort';runner.write(cohort/'prepared.json',dict(cases=cases));runner.write(cohort/'seal.json',runner.frozen(cohort/'prepared.json'))
    deadline=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat();inherited=tmp_path/'r18'
    original.prepare(SimpleNamespace(source_cohort=cohort,output=inherited,deadline_utc=deadline))
    (inherited/'cases/trial00/generation/decoded.json').write_text('FORBIDDEN_GENERATED_RESULTS')
    target=tmp_path/'r30'
    result=runner.prepare(SimpleNamespace(source_cohort=inherited,output=target,deadline_utc=deadline))
    assert result['trials']==17 and result['requests']==2 and result['slots']==6
    return SimpleNamespace(input=target)


def provider(calls,fault=None):
    def dispatch(request,output,*,root):
        payload=json.loads(request['prompt']);selection=request['kind']==runner.relation.VERSION
        calls.append('selection' if selection else 'review')
        finish='stop'
        if selection:
            hosts={h['host_id']:h for h in payload['hosts']}
            content=json.dumps(dict(selections=[dict(slot=s['slot'],projection_ids=[p['id'] for p in hosts[s['host_id']]['projections'] if p['field']=='phase']) for s in payload['slots']]))
            if fault=='empty':content='{"selections":[]}'
            if fault=='length':finish='length'
        else:
            content=json.dumps(dict(basis='fixture contract',judgments={k:('unknown' if fault=='domain' and k=='R_DOMAIN' else 'supported') for k in request['check_ids']}))
        output.mkdir();runner.write(output/'request.json',dict(messages=[dict(role='system',content=request['system']),dict(role='user',content=request['prompt'])],max_tokens=request['max_tokens'],thinking=dict(type=request['thinking']),reasoning_effort=request['reasoning_effort'],model='fixture'))
        raw=dict(model='fixture',usage=dict(total_tokens=100),choices=[dict(message=dict(content=content),finish_reason=finish)]);body=json.dumps(raw).encode()
        (output/'response.body').write_bytes(body);runner.write(output/'response.json',raw);(output/'completion.txt').write_text(content)
        runner.write(output/'manifest.json',dict(status='complete',external_model_calls=1,request_id=request['id'],request_sha256=original.admission.digest(output/'request.json'),response_sha256=hashlib.sha256(body).hexdigest(),model='fixture',response_model='fixture',finish_reason=finish,usage=dict(total_tokens=100)))
    return dispatch


def test_full_stages_keep_raw_costs_controls_and_first_failure_repeat(tmp_path,monkeypatch):
    before=(original.VERSION,original.relation,original.review,original.dispatch)
    args=prepared(tmp_path);calls=[];monkeypatch.setattr(runner,'dispatch',provider(calls))
    result=runner.select(args);assert result['candidates']==6 and calls==['selection','selection']
    native=SimpleNamespace(input=args.input/'native')
    protocol=runner.read(native.input/'prepared.json')
    for case in protocol['cases'][:2]:
        assert [e['rank'] for e in case['candidates']]==[1,2,3]
        for entry in case['candidates']:
            request=runner.read(entry['request']['path'])
            assert request['reasoning_effort']=='high' and request['max_tokens']==16384
            assert set(runner.review.OBLIGATIONS).issubset(request['check_ids'])
            assert 'FORBIDDEN_GENERATED_RESULTS' not in request['prompt']
    assert runner.review_all(native)['admitted']==6
    runs=[]
    def run(candidate,source,corpus,target,protocol):
        runs.append((Path(source).name,candidate['order'][0]))
        outcome=dict(transport=dict(status='matched'),native=dict(controls=dict(status='all_source_controls_passed'),controlled_failure=True))
        runner.write(target/'native_outcome.json',dict(fixture=True));runner.write(target/'outcome.json',outcome);return outcome
    monkeypatch.setattr(runner,'one_run',run)
    summary=runner.run(native)
    assert summary['generation_model_calls']==2 and summary['semantic_review_model_calls']==6
    assert runs==[('0',1),('0',1),('1',1),('1',1)]
    runner.select(args);runner.run(native)
    assert len(calls)==8 and len(runs)==4
    assert before==(original.VERSION,original.relation,original.review,original.dispatch)


@pytest.mark.parametrize('fault',['empty','length','domain'])
def test_abstention_or_missing_domain_support_never_admits(tmp_path,monkeypatch,fault):
    args=prepared(tmp_path);calls=[];monkeypatch.setattr(runner,'dispatch',provider(calls,fault))
    result=runner.select(args)
    if fault!='domain':assert result['candidates']==0
    assert runner.review_all(SimpleNamespace(input=args.input/'native'))['admitted']==0


def test_raw_receipt_tamper_blocks_replay(tmp_path,monkeypatch):
    args=prepared(tmp_path);monkeypatch.setattr(runner,'dispatch',provider([]));runner.select(args)
    (args.input/'cases/trial00/generation/completion/completion.txt').write_text('{"selections":[]}')
    with pytest.raises(ValueError):runner.select(args)
