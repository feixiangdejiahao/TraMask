import hashlib

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from relation_search import oracle
from relation_search.type_observer_projection import project


def fixture():
    code="test('schema', () => { const schema = build(); expect(schema.entries.item).toBe(schema); expect(parse(schema, input)).toEqual(input); });"
    source=Source('test.ts',code,'typescript');frontend=extract_frontend([source]);corpus=to_emitter_corpus(frontend);base=next(iter(corpus['tests']));at=code.index('build()')
    candidate=dict(id='fixed',base_test_id=base,edits=[dict(span=dict(path='test.ts',start_byte=at,end_byte=at+7),before='build()',after='wrap(build())',role='input')])
    emitted=oracle.preview(corpus,candidate);start=emitted.index('entries')
    report=dict(status='compiler_completed',target='test.ts',configuration=dict(parse_errors=[]),
        phases=[dict(role='generated',source_sha256=hashlib.sha256(emitted.encode()).hexdigest(),options_diagnostics=[])],
        new_diagnostics=[dict(category='Error',code=2339,start_utf16=start,end_utf16=start+7,source='entries')])
    return corpus,frontend,candidate,report,emitted


def test_projection_removes_only_type_invalid_pure_assertion_and_keeps_calls():
    corpus,frontend,candidate,report,emitted=fixture();result=project(corpus,frontend,candidate,report,emitted)
    assert result['status']=='projected';text=oracle.preview(corpus,result['candidate'])
    assert 'wrap(build())' in text and 'parse(schema, input)' in text
    assert 'schema.entries' not in text
    assert result['candidate']['edits'][0]==candidate['edits'][0]


def test_input_call_type_errors_cannot_be_hidden_by_projection():
    corpus,frontend,candidate,report,emitted=fixture();start=emitted.index('build()')
    report['new_diagnostics'][0].update(start_utf16=start,end_utf16=start+7)
    assert project(corpus,frontend,candidate,report,emitted)['candidate'] is None


def test_stale_compiler_evidence_cannot_modify_a_test():
    corpus,frontend,candidate,report,emitted=fixture()
    assert project(corpus,frontend,candidate,report,emitted+' ')['reason']=='compiler_source_mismatch'
