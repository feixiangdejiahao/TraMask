"""Failure diagnostics with mock responses; never contacts a model provider."""
import json
import socket

import httpx
import pytest

from generic_composition import gate


CANDIDATES=[{'id':'synthetic-id','edits':[{'before':'assert f(1)==2','after':'assert f([1])==[2]'}]}]


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Real network is forbidden in gate diagnostic unit tests")
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)


def provider(monkeypatch,tmp_path,raw=None,exc=None):
    (tmp_path/'configs').mkdir()
    (tmp_path/'configs/execution_policy.json').write_text('{"allow_model_code_upload":true}')
    monkeypatch.setattr(gate,'ROOT',tmp_path)
    monkeypatch.setattr(gate,'dotenv_values',lambda _: {'base_url':'https://unit.invalid/v1','api_key':'unit-placeholder'})
    calls=[]
    original_client=httpx.Client
    def handle(request):
        calls.append(json.loads(request.content))
        if exc is not None: raise exc
        return httpx.Response(200,json=raw)
    transport=httpx.MockTransport(handle)
    def client(*args,**kwargs):
        return original_client(*args,transport=transport,**kwargs)
    monkeypatch.setattr(gate.httpx,'Client',client)
    return calls


def response(content,finish='stop',reasoning=None,details=None):
    raw={'model':'deepseek-v4-flash','choices':[{'message':{'content':content},'finish_reason':finish}],
         'usage':{'completion_tokens_details':details}}
    if reasoning is not None: raw['choices'][0]['message']['reasoning_content']=reasoning
    return raw


@pytest.mark.parametrize('content,finish,reasoning,details,kind',[
    (None,'length','synthetic reasoning',None,'no_final_reasoning_limit'),
    ('','length',None,{'reasoning_tokens':9},'no_final_reasoning_limit'),
    (' \n','length',None,{'reasoning_tokens':9},'no_final_reasoning_limit'),
    (None,'length',None,None,'no_final_completion_limit'),
    ('','length',' \t',{'reasoning_tokens':0},'no_final_completion_limit'),
    (None,'length',None,{'reasoning_tokens':'9'},'no_final_completion_limit'),
    (None,'length',None,{'reasoning_tokens':True},'no_final_completion_limit'),
    (None,'stop','synthetic reasoning',None,'no_final_reasoning_only'),
    (None,'stop',None,None,'no_final'),
    ('{"accepted":[','length',None,None,'invalid_final_json_at_limit'),
    ('not JSON','stop',None,None,'invalid_final_json'),
    ('{"accepted":["unknown"]}','stop',None,None,'invalid_selection_schema'),
    ('{"accepted":["c0","c0"]}','stop',None,None,'invalid_selection_schema'),
    ('{"accepted":[],"code":"new code"}','stop',None,None,'invalid_selection_schema'),
    ([], 'stop',None,None,'invalid_final_content_type'),
    (False,'stop',None,None,'invalid_final_content_type'),
])
def test_failure_kind_preserves_original_validation_and_request(monkeypatch,tmp_path,content,finish,reasoning,details,kind):
    calls=provider(monkeypatch,tmp_path,response(content,finish,reasoning,details))
    output=tmp_path/'admission'
    result=gate.request_admission({'issue':'toy requirement'},CANDIDATES,output)
    assert result['valid'] is False and result['failure_kind']==kind
    assert isinstance(result['validation_error'],str) and 'accepted' not in result
    assert result['external_model_calls']==len(calls)==1
    assert calls[0]['model']=='deepseek-v4-flash'
    assert calls[0]['thinking']=={'type':'disabled'} and calls[0]['reasoning_effort']=='none'
    assert calls[0]['response_format']=={'type':'json_object'} and calls[0]['max_tokens']==10000
    assert json.loads((output/'manifest.json').read_text())==result
    with pytest.raises(ValueError,match='No valid'):
        gate.load_admission(output,CANDIDATES)


@pytest.mark.parametrize('finish',['stop','length'])
def test_valid_selection_keeps_legacy_admission_even_with_length(monkeypatch,tmp_path,finish):
    calls=provider(monkeypatch,tmp_path,response('{"accepted":["c0"]}',finish))
    output=tmp_path/'admission'
    result=gate.request_admission({},CANDIDATES,output)
    assert result['valid'] and result['accepted']==['synthetic-id']
    assert 'failure_kind' not in result and len(calls)==1
    assert gate.load_admission(output,CANDIDATES)==result


def test_transport_error_retains_exception_class_and_no_retry(monkeypatch,tmp_path):
    calls=provider(monkeypatch,tmp_path,exc=httpx.ReadTimeout('synthetic timeout'))
    result=gate.request_admission({},CANDIDATES,tmp_path/'admission')
    assert result['valid'] is False and result['transport_error']=='ReadTimeout'
    assert result['failure_kind']=='transport_error' and len(calls)==1


def test_bad_envelope_retains_exception_class(monkeypatch,tmp_path):
    calls=provider(monkeypatch,tmp_path,{'choices':[]})
    result=gate.request_admission({},CANDIDATES,tmp_path/'admission')
    assert result['valid'] is False and result['response_error']=='IndexError'
    assert result['failure_kind']=='invalid_response_envelope' and len(calls)==1


def test_credentials_keep_configuration_exception_before_dispatch(monkeypatch,tmp_path):
    calls=provider(monkeypatch,tmp_path)
    monkeypatch.setattr(gate,'dotenv_values',lambda _: {})
    output=tmp_path/'admission'
    with pytest.raises(RuntimeError,match='credentials'):
        gate.request_admission({},CANDIDATES,output)
    result=json.loads((output/'manifest.json').read_text())
    assert result['configuration_error']=='MissingProviderCredentials'
    assert result['failure_kind']=='configuration_error'
    assert not calls and result['external_model_calls']==0
