from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from relation_search import oracle
from relation_search.test_prefix_projection import construct
import copy


def fixture(code,language,before,after):
    source=Source(dict(python='test_flow.py',go='flow_test.go',typescript='flow.test.ts')[language],code,language)
    frontend=extract_frontend([source]);corpus=to_emitter_corpus(frontend);base=next(iter(corpus['tests']))
    at=code.index(before);candidate=dict(id='fixed',base_test_id=base,edits=[dict(span=dict(path=source.path,start_byte=at,end_byte=at+len(before)),before=before,after=after,role='input')])
    return corpus,frontend,candidate


def test_python_prefix_preserves_nested_resource_scope_and_input():
    args=fixture('def test_flow():\n    with resource() as item:\n        use(item, 2)\n        assert item.ok\n    assert opaque_id() == 1\n', 'python','use(item, 2)','use(item, 3)')
    rows=construct(*args)['candidates'];assert len(rows)==1
    code=oracle.preview(args[0],rows[0]);assert 'with resource() as item:' in code and 'use(item, 3)' in code
    assert 'assert item.ok' in code and 'opaque_id' not in code


def test_prefix_cannot_discard_a_later_input_edit():
    args=fixture('def test_flow():\n    assert first()\n    use(2)\n    assert second()\n    assert last()\n','python','use(2)','use(3)')
    out=construct(*args);assert out['skipped'][0]['reason']=='would_remove_input_edit'
    assert all('use(3)' in oracle.preview(args[0],row) for row in out['candidates'])


def test_go_and_typescript_prefixes_preserve_closing_syntax():
    for language,code in [('go','package p\nfunc TestFlow(t *testing.T) { use(2); require.True(t, value); finish(); require.Equal(t, 1, id) }'),('typescript',"test('flow', () => { use(2); expect(value).toBe(true); finish(); expect(id).toBe(1); });")]:
        args=fixture(code,language,'use(2)','use(3)');rows=construct(*args)['candidates'];assert rows
        rendered=oracle.preview(args[0],rows[0]);assert 'use(3)' in rendered and 'finish()' not in rendered
        assert not Source('projected',('package p\n' if language=='go' else '')+rendered,language).root.has_error


def test_oracle_revisions_in_removed_continuation_do_not_remove_input():
    args=fixture('def test_flow():\n    use(2)\n    assert first()\n    assert second() == 1\n','python','use(2)','use(3)')
    corpus,frontend,candidate=args;code=next(iter(corpus['sources'].values()))['code'];at=code.rindex('1')
    candidate['edits'].append(dict(span=dict(path='test_flow.py',start_byte=at,end_byte=at+1),before='1',after='4',role='semantic_expected'))
    rows=construct(corpus,frontend,candidate)['candidates'];assert len(rows)==1
    assert rows[0]['prefix_projection']['removed_oracle_edits']==1
    assert candidate['edits'][0] in rows[0]['edits']


def test_historical_instrumentation_cannot_restore_the_deleted_suffix():
    args=fixture('def test_flow():\n    use(2)\n    assert first()\n    assert second()\n','python','use(2)','use(3)')
    corpus,frontend,candidate=args
    candidate.update(program_edits=copy.deepcopy(candidate['edits']),instrumentation={'status':'instrumented'},runtime_probes=[{'old':'measurement'}])
    revised=construct(corpus,frontend,candidate)['candidates'][0]
    assert 'instrumentation' not in revised and 'runtime_probes' not in revised
    assert oracle.program_candidate(revised)['edits']==revised['edits']
    assert 'second()' not in oracle.preview(corpus,oracle.program_candidate(revised))
