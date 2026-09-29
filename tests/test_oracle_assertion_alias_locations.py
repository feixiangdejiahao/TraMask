import json

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.impact_selection import select
from relation_search.oracle import prepare_requests


def test_duplicate_assertions_keep_distinct_phase_ids_after_length_changes_and_insertion():
    code='''def calculate(value):
    return value

def test_phases():
    result = calculate(1)
    assert result == 1
    result = calculate(1)
    assert result == 1
'''
    source=Source('test_phases.py',code,'python')
    frontend=extract_frontend([source]);corpus=to_emitter_corpus(frontend)
    test=next(iter(corpus['tests'].values()))
    edits=[]
    start=0
    while True:
        at=code.find('calculate(1)',start)
        if at<0:break
        point=at+len('calculate(')
        edits.append(dict(span=dict(path=source.path,start_byte=point,end_byte=point+1),
                          before='1',after='100',role='input'))
        start=at+len('calculate(1)')
    insert=code.index('result = calculate(1)',code.index('assert result == 1'))
    edits.append(dict(span=dict(path=source.path,start_byte=insert,end_byte=insert),
                      before='',after="marker = '阶段'\n    ",role='state_prefix'))
    candidate=dict(id='changed_phases',base_test_id=test['id'],source_test_ids=[],imports=[],edits=edits)
    ranked=select(corpus,frontend,[candidate],1)['ranking'][0]
    request=prepare_requests(corpus,frontend,[candidate],'Check both observations.',
        evidence_mode='dependency',impact_evidence_by_id={candidate['id']:ranked['evidence']})[0]
    wire=json.loads(request['prompt'])['candidates'][0]
    assertions=wire['assertions']
    assert [a['code'] for a in assertions] == ['assert result == 1','assert result == 1']
    assert [a['id'] for a in assertions] == ['A0','A1']
    assert assertions[0]['original_span'] != assertions[1]['original_span']
    assert assertions[0]['modified_span']['start_byte']-assertions[0]['original_span']['start_byte']==2
    assert assertions[1]['modified_span']['start_byte']-assertions[1]['original_span']['start_byte']==4+len(edits[-1]['after'].encode())
    evidence=request['analysis_evidence']['C0']
    assert {q['assertion_alias'] for q in evidence['assertions']} == {'A0','A1'}
    assert {q['assertion_alias'] for q in evidence['original_observation_obligations']} == {'A0','A1'}
    assert '[A0]' in wire['dependency_evidence']['rendered'] and '[A1]' in wire['dependency_evidence']['rendered']
