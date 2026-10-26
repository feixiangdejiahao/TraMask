"""Recorded dispatch preserves omissions and never silently repeats a call."""
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from prototypes.finite_oracle_questions import build_question
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.provider import encoded
from scripts import run_finite_oracle_pairs as driver
from scripts.prepare_finite_oracle_pairs import wire_preview


@pytest.fixture
def prepared(tmp_path):
    code = 'def test_case():\n    value = 2\n    assert value == 2\n'
    front = extract_frontend([Source('test_case.py',code,'python')])
    corpus = to_emitter_corpus(front)
    base = next(iter(corpus['tests']))
    begin = code.index('value = 2')+len('value = ')
    candidates = [dict(id='member_'+str(v),base_test_id=base,imports=[],edits=[dict(
        span=dict(path='test_case.py',start_byte=begin,end_byte=begin+1),
        before='2',after=str(v),role='input')]) for v in [2,3]]
    source = tmp_path/'source';source.mkdir()
    driver.write(source/'corpus.json',corpus)
    request = build_question(corpus,front,candidates,'Assignment defines value.')
    request['source_prepared'] = str(source)
    path = tmp_path/'request.json';driver.write(path,request)
    return path,tmp_path/'completion'


def install_provider(monkeypatch, response, status='complete'):
    calls = []
    def recorded(request,output,root):
        calls.append(request['id'])
        output.mkdir()
        wire = encoded(wire_preview(request));(output/'request.json').write_bytes(wire)
        record = dict(status=status,request_id=request['id'],request_sha256=hashlib.sha256(wire).hexdigest(),
                      external_model_calls=1,usage={'total_tokens':10})
        driver.write(output/'manifest.json',record)
        if status=='complete': (output/'completion.txt').write_text(json.dumps(response))
        return record
    monkeypatch.setattr(driver,'dispatch',recorded)
    return calls


def test_resume_uses_the_same_answer_without_resending_and_preserves_omission(prepared,monkeypatch):
    calls = install_provider(monkeypatch,dict(results=[dict(candidate='C0',status='keep',updates=[],basis='value is two')]))
    first = driver.complete(*prepared)
    second = driver.complete(*prepared)
    assert first==second and len(calls)==1
    assert first['answered_members']==1 and first['offered_members']==2
    assert not first['all_members_answered']
    outcome = driver.read(prepared[1]/'validation.json')
    assert [r['status'] for r in outcome['members']]==['keep','unanswered']
    assert all(r['semantic_correctness']=='unreviewed' for r in outcome['members'])


def test_provider_failure_is_terminal_and_never_counts_as_correct_keep(prepared,monkeypatch):
    calls = install_provider(monkeypatch,None,status='error')
    first = driver.complete(*prepared);second = driver.complete(*prepared)
    assert first==second and len(calls)==1
    assert first['status']=='error' and first['answered_members']==0
    assert not (prepared[1]/'validation.json').exists()


def test_nonterminal_attempt_requires_live_audit_before_resume(prepared,monkeypatch):
    calls = install_provider(monkeypatch,None,status='dispatching')
    driver.complete(*prepared)
    with pytest.raises(ValueError,match='unfinished attempt'):
        driver.complete(*prepared)
    assert len(calls)==1


def test_existing_receipt_for_other_request_is_rejected_without_call(prepared,monkeypatch):
    calls = install_provider(monkeypatch,dict(results=[]))
    driver.complete(*prepared)
    manifest = driver.read(prepared[1]/'manifest.json');manifest['request_id']='another'
    driver.write(prepared[1]/'manifest.json',manifest)
    with pytest.raises(ValueError,match='another request'):
        driver.complete(*prepared)
    assert len(calls)==1


def test_wire_mutation_is_rejected_even_when_response_is_present(prepared,monkeypatch):
    calls = install_provider(monkeypatch,dict(results=[]))
    driver.complete(*prepared)
    path = prepared[1]/'request.json';wire=driver.read(path);wire['model']='other'
    path.write_bytes(encoded(wire))
    with pytest.raises(ValueError,match='sealed preview'):
        driver.complete(*prepared)
    assert len(calls)==1
