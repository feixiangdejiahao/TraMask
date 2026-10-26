"""Offline replay cannot invent model responses or relax observation bindings."""
import copy
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from prototypes.assertion_operand_guard import valid_assertion
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.oracle import prepare_requests
from scripts.audit_go_predicate_readmission import (audit_completion, predicate_only_change,
                                                    relaxed_updates, validate_with_guard)


def legacy_guard(code, old, observed, language):
    if language == 'go' and any('.'+name+'(' in old for name in ['NoError', 'Error']):
        return False
    return valid_assertion(code, old, observed, language)


def sample():
    source = Source('sample_test.go', '''package sample
func TestOperation(t *testing.T) {
    err := operation(10)
    require.NoError(t, err, "雪: %v", err)
}
''', 'go')
    frontend = extract_frontend([source]);corpus=to_emitter_corpus(frontend)
    test_id=next(iter(corpus['tests']));start=source.data.index(b'10')
    candidate=dict(id='edit',base_test_id=test_id,imports=[],edits=[dict(
        span=dict(path=source.path,start_byte=start,end_byte=start+2),before='10',after='20',role='input')])
    request=prepare_requests(corpus,frontend,[candidate],'An invalid input reports an error.',max_requests=1)[0]
    hole=next(hid for hid,h in request['offered']['C0']['assertions'].items() if 'NoError' in h['code'])
    old=request['offered']['C0']['assertions'][hole]['code']
    update = dict(assertion=hole, code=old.replace('.NoError(', '.Error('))
    completion=json.dumps(dict(revisions=[dict(candidate='C0',basis='Input crosses the documented boundary.',
                                               updates=[update])]))
    return request,completion,corpus


@pytest.mark.parametrize('before,after,observed',[
 ('require.NoError(t, read(), "雪", details())','require.Error(t, read(), "雪", details())','read()'),
 ('assert.False(t, flags[0])','assert.True(t, flags[0])','flags[0]'),
 ('assert.NotNil(t, item)','assert.Nil(t, item)','item'),
 ('require.Empty(t, values)','require.NotEmpty(t, values)','values')])
def test_independent_ast_check_accepts_only_fixed_predicate_pair(before,after,observed):
    assert predicate_only_change(before,after,observed)


@pytest.mark.parametrize('after',[
 'assert.Error(t, err, "same", details)',
 'require.Error(other, err, "same", details)',
 'require.Error(t, other, "same", details)',
 'require.Error(t, err, "different", details)',
 'require.Error(t, err, "same", other)',
 'require.Error(t, err)',
 'require.Error(t, err, "same", details, extra)',
 'require.NotNil(t, err, "same", details)',
 'require.Error(t, err, "same", details); act()',
 'require.Error(t, err, "same", details)\nrequire.Error(t, other)'])
def test_independent_check_rejects_changes_to_other_tokens(after):
    before='require.NoError(t, err, "same", details)'
    assert not predicate_only_change(before,after,'err')


def test_replay_uses_exact_existing_response_and_does_not_mutate_source_records():
    request,completion,corpus=sample();before=copy.deepcopy((request,corpus))
    old=validate_with_guard(request,completion,corpus,legacy_guard)
    new=validate_with_guard(request,completion,corpus)
    assert old['decisions'][0]['status']=='rejected_structure' and not old['revisions']
    assert len(new['revisions'])==1
    assert new['revisions'][0]['semantic_revision']['validity']=='unconfirmed'
    assert new['revisions'][0]['edits'][:-1]==request['offered']['C0']['candidate']['edits']
    relaxed=relaxed_updates(request,completion,legacy_guard)
    assert len(relaxed)==1 and relaxed[0]['independently_verified_predicate_only']
    assert (request,corpus)==before


def encoded(value):
    return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'))+'\n').encode()


def fixture(tmp_path):
    request,completion,corpus=sample();directory=tmp_path/'completion';directory.mkdir()
    request_path=tmp_path/'request.json';request_path.write_bytes(encoded(request))
    corpus_path=tmp_path/'corpus.json';corpus_path.write_bytes(encoded(corpus))
    wire=dict(messages=[dict(role='system',content=request['system']),dict(role='user',content=request['prompt'])])
    (directory/'request.json').write_bytes(encoded(wire))
    response=dict(choices=[dict(message=dict(content=completion))])
    body=encoded(response)
    (directory/'response.body').write_bytes(body);(directory/'response.json').write_bytes(body)
    (directory/'completion.txt').write_text(completion)
    (directory/'validation.json').write_bytes(encoded(validate_with_guard(request,completion,corpus,legacy_guard)))
    manifest=dict(status='complete',request_id=request['id'],
        request_sha256=hashlib.sha256(encoded(wire)).hexdigest(),response_sha256=hashlib.sha256(body).hexdigest())
    (directory/'manifest.json').write_bytes(encoded(manifest))
    return request_path,directory,corpus_path


def test_complete_record_keeps_full_before_after_and_rejects_completion_tampering(tmp_path):
    request,directory,corpus=fixture(tmp_path)
    outcome=audit_completion(request,directory,corpus,legacy_guard)
    assert outcome['legacy_reproduces_recorded'] and outcome['only_predicate_admission_changed']
    assert len(outcome['newly_admitted_revisions'])==1 and outcome['removed_revision_ids']==[]
    assert outcome['files_sha256'][str(corpus.resolve())]
    (directory/'completion.txt').write_text('{"revisions":[]}')
    with pytest.raises(ValueError,match='completion does not match'):
        audit_completion(request,directory,corpus,legacy_guard)


def test_noncomplete_responses_are_retained_without_fabricated_validation(tmp_path):
    request,directory,corpus=fixture(tmp_path)
    path=directory/'manifest.json';manifest=json.loads(path.read_text());manifest['status']='error'
    path.write_bytes(encoded(manifest));(directory/'completion.txt').unlink()
    result=audit_completion(request,directory,corpus,legacy_guard)
    assert not result['replayed'] and result['provider_status']=='error'
    assert 'current_validation' not in result


def test_malformed_payload_remains_an_error_not_an_admitted_revision():
    request,_,corpus=sample()
    result=validate_with_guard(request,'not json',corpus)
    assert result==dict(revisions=[],decisions=[],error='JSONDecodeError')
