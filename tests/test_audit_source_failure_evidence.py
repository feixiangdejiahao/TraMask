from collections import Counter
import hashlib
import json

import pytest

from scripts.audit_source_failure_evidence import audit_member


def fixture():
    caller = 'package caller\nimport q "example/checks"\nfunc Test(t any) { q.Moon(t) }\n'
    api = 'package checks\nimport "testing"\nfunc Moon(t *testing.T) { t.FailNow() }\n'

    def extent(path, code, text):
        start = code.index(text)
        return dict(path=path, start_byte=start, end_byte=start+len(text))

    declaration = 'func Moon(t *testing.T) { t.FailNow() }'
    formal = dict(name='t', span=extent('checks/api.go',api,'t *testing.T'))
    formal['span']['end_byte'] = formal['span']['start_byte']+1
    function = dict(id='f',name='Moon',status='source_function',parameters=[formal],code=declaration,
        span=extent('checks/api.go',api,declaration),source_sha256=hashlib.sha256(api.encode()).hexdigest())
    sink = dict(id='sink',caller_id='f',target_id=None,status='testing_sink',callee='t.FailNow',
        code='t.FailNow()',span=extent('checks/api.go',api,'t.FailNow()'))
    binding = dict(status='source_bound',module='example/checks',declaration_name='Moon',
        declaration_code=declaration,declaration_span=function['span'],
        declaration_source_sha256=function['source_sha256'],
        declaration_sha256=hashlib.sha256(declaration.encode()).hexdigest(),
        import_code='q "example/checks"',import_span=extent('caller_test.go',caller,'q "example/checks"'),actual_formal=[])
    proof = dict(function=function,can_reach_failure=True,reachable_functions=[function],same_package_calls=[sink],
        sink_evidence=[dict(call_id='sink',code=sink['code'],span=sink['span'])],conditions=[],unknowns=[],
        shortest_failure_paths=[[sink]],limits=['source facts only'])
    result = dict(calls=[dict(code='q.Moon(t)',span=extent('caller_test.go',caller,'q.Moon(t)'),instances=[{}],
        binding=binding,failure_evidence=proof,expected_port_status='unknown')])
    return {'caller_test.go':caller.encode(),'checks/api.go':api.encode()},dict(edits=[]),json.loads(json.dumps(result))


def test_saved_auditor_recovers_source_independently():
    original,candidate,result = fixture()
    counts = Counter()
    status,_,shape = audit_member(original,candidate,'caller_test.go',result,counts)
    assert counts['call_sites']==1 and counts['failure_paths_verified']==1
    assert status=={'source_function':1}
    assert next(iter(shape.values()))['paths']==[['Moon','t.FailNow']]


@pytest.mark.parametrize('damage,match',[
    ('function_code','exact source span'),
    ('path_copy','canonical source call'),
    ('path_caller','discontinuity'),
    ('sink_removed','confirmed sink endpoint'),
    ('source_sha','source SHA mismatch'),
])
def test_saved_auditor_rejects_damaged_code_path_or_sha(damage,match):
    original,candidate,result = fixture()
    proof = result['calls'][0]['failure_evidence']
    if damage=='function_code':proof['reachable_functions'][0]['code']='invented()'
    elif damage=='path_copy':proof['shortest_failure_paths'][0][0]['callee']='other.FailNow'
    elif damage=='path_caller':
        proof['same_package_calls'][0]['caller_id']='other'
        proof['shortest_failure_paths'][0][0]['caller_id']='other'
    elif damage=='sink_removed':proof['sink_evidence']=[]
    else:proof['reachable_functions'][0]['source_sha256']='wrong'
    with pytest.raises(ValueError,match=match):
        audit_member(original,candidate,'caller_test.go',result,Counter())
