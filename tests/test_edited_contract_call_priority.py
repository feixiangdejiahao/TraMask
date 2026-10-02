import copy

import pytest

from relation_search.edited_contract_call_priority import Analyzer, issue_names, select


def fixture(code, actual, before, after, *, language='python', path='test_sample.py', occurrence=0, role='input', extra=None):
    start=code.index(before) if occurrence==0 else code.rindex(before)
    position=code.rindex(actual)
    corpus=dict(language=language,sources={path:dict(code=code)},tests={'seed':dict(
        span=dict(path=path,start_byte=0,end_byte=len(code.encode())),retrieval_rank=1)})
    def byte(value):return len(code[:value].encode())
    frontend=dict(calls=[],functions=[],observations=[dict(id='q',test_id='seed',kind='assertion',
        observed=dict(span=dict(path=path,start_byte=byte(position),end_byte=byte(position+len(actual)))) )])
    if extra:frontend.update(extra)
    candidate=dict(id='candidate',base_test_id='seed',kind='input',imports=[],relation={},edits=[dict(
        before=before,after=after,role=role,span=dict(path=path,start_byte=byte(start),end_byte=byte(start+len(before))))])
    return corpus,frontend,candidate


def evidence(code,actual,before='1',after='2',issue='Change `parse()`.',**kwargs):
    corpus,frontend,candidate=fixture(code,actual,before,after,**kwargs)
    return Analyzer(corpus,frontend,issue).evidence(candidate)


def test_code_api_names_are_not_prose_keyword_counts():
    assert issue_names('parse parse parse; change `parse()` and `Client.read`.\n```py\nx = transform(v)\n```')==['Client.read','parse','transform']
    assert not issue_names('parse should parse input and return parsed output')


@pytest.mark.parametrize('code,actual,language,path',[
    ('from toolkit import parse\ndef test_x():\n    assert parse(1) == 4\n','parse(1)','python','test_sample.py'),
    ('import {parse} from "./toolkit"; test("x",()=>{expect(parse(1)).toBe(4);});','parse(1)','typescript','sample.test.ts'),
    ('package x\nimport api "example/toolkit"\nfunc TestX(t *testing.T) { r:=api.Parse(1); require.Equal(t,4,r) }','r','go','sample_test.go'),
])
def test_direct_edited_call_observation_across_languages(code,actual,language,path):
    row=evidence(code,actual,language=language,path=path,issue='Change `Parse()` and `parse()`.')
    assert row['feature'],row


def test_one_input_binding_and_assigned_return_are_supported():
    code='from toolkit import parse\ndef test_x():\n    value = 1\n    result = parse(value)\n    assert result == 4\n'
    row=evidence(code,'result')
    assert row['feature']
    assert row['witnesses'][0]['input_basis']=='one_local_assignment'
    assert row['witnesses'][0]['observation_basis']=='assigned_return_read'


def test_two_hop_input_binding_is_deliberately_not_followed():
    code='from toolkit import parse\ndef test_x():\n    initial = 1\n    value = initial\n    result = parse(value)\n    assert result == 4\n'
    assert not evidence(code,'result')['feature']


def test_edited_first_call_cannot_borrow_second_calls_observation():
    code='from toolkit import parse\ndef test_x():\n    first = parse(1)\n    second = parse(3)\n    assert second == 4\n'
    assert not evidence(code,'second')['feature']


def test_reassigned_return_does_not_observe_earlier_call():
    code='from toolkit import parse\ndef test_x():\n    result = parse(1)\n    result = 4\n    assert result == 4\n'
    assert not evidence(code,'result')['feature']


def test_expected_edit_and_unrelated_whole_test_api_do_not_count():
    code='from toolkit import parse, other\ndef test_x():\n    unused = parse(3)\n    result = other(1)\n    assert result == 4\n'
    assert not evidence(code,'result')['feature']
    direct='from toolkit import parse\ndef test_x():\n    assert parse(1) == 4\n'
    assert not evidence(direct,'parse(1)',before='4',after='5',role='semantic_expected')['feature']


def test_import_alias_resolves_to_contract_name():
    code='from toolkit import parse as renamed\ndef test_x():\n    assert renamed(1) == 4\n'
    assert evidence(code,'renamed(1)')['feature']


def test_shadowed_import_is_not_a_contract_call():
    code='from toolkit import parse\ndef test_x():\n    parse = other\n    assert parse(1) == 4\n'
    assert not evidence(code,'parse(1)')['feature']


def test_later_assignment_still_shadows_python_import():
    code='from toolkit import parse\ndef test_x():\n    assert parse(1) == 4\n    parse = other\n'
    assert not evidence(code,'parse(1)')['feature']


def test_conditional_binding_is_not_a_proved_one_hop_value():
    code='from toolkit import parse\ndef test_x():\n    if condition:\n        value = 1\n    result = parse(value)\n    assert result == 4\n'
    assert not evidence(code,'result')['feature']


def method_fixture(actual='r.closed',rebind='',before_observation=False):
    body=f'    r = Client()\n    other = Client()\n'
    if before_observation:body+=f'    assert {actual}\n'
    body+='    r.consume(1)\n'+rebind
    if not before_observation:body+=f'    assert {actual}\n'
    code='def test_x():\n'+body
    start=code.index('r.consume(1)')
    extra=dict(functions=[dict(id='client.py:1:Client.consume',owner='Client',name='consume')],calls=[dict(
        test_id='seed',span=dict(path='test_sample.py',start_byte=start,end_byte=start+len('r.consume(1)')),
        callee='r.consume',callee_identity=dict(canonical='client.py::Client.consume'),
        targets=[dict(function_id='client.py:1:Client.consume',resolved=True)])])
    return fixture(code,actual,'1','2',extra=extra)


def test_same_receiver_field_is_observed_after_call():
    c,f,k=method_fixture();row=Analyzer(c,f,'Change `Client.consume`.').evidence(k)
    assert row['feature'],row
    assert row['witnesses'][0]['observation_basis']=='same_unrebound_receiver_field'


@pytest.mark.parametrize('actual,rebind,early',[
    ('other.closed','',False),('r.closed','    r = Client()\n',False),('r.closed','',True),
])
def test_receiver_and_phase_cannot_be_borrowed(actual,rebind,early):
    c,f,k=method_fixture(actual,rebind,early)
    assert not Analyzer(c,f,'Change `Client.consume`.').evidence(k)['feature']


def test_unicode_offsets_and_equal_expected_literals():
    code='from toolkit import parse\n# 中文\ndef test_x():\n    result = parse(1)\n    assert result == 1\n'
    assert evidence(code,'result')['feature']


def test_invalid_source_edits_remain_explicit_unknown():
    code='from toolkit import parse\ndef test_x():\n    assert parse(1) == 4\n'
    c,f,k=fixture(code,'parse(1)','1','2');k['edits'][0]['before']='bad'
    row=Analyzer(c,f,'`parse`').evidence(k)
    assert not row['feature'] and row['status']=='unknown'


def test_stable_partition_preserves_baseline_within_buckets_and_ignores_labels():
    code='from toolkit import parse, other\ndef test_x():\n    first = parse(1)\n    result = other(3)\n    assert first == 4\n'
    c,f,a=fixture(code,'first','1','2');_,_,b=fixture(code,'first','3','5');b['id']='other'
    original=copy.deepcopy((c,f,[a,b]))
    result=select(c,f,[a,b],'`parse`',budget=1)
    assert [row['id'] for row in result['ranking']]==['candidate','other']
    annotated=copy.deepcopy([b,a])
    for row in annotated:row.update(evaluation={'target':row['id']=='other'},runtime_outcome='failed',oracle={'accepted':True})
    again=select(c,f,annotated,'`parse`',budget=1)
    assert result['ranking']==again['ranking']
    assert (c,f,[a,b])==original
    assert len(select(c,f,[a,b],'`parse`',budget=0)['ranking'])==2
