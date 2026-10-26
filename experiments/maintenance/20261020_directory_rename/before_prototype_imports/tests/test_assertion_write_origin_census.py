import ast
from unittest.mock import patch

from experimental.assertion_write_origin import Index
from scripts.analyze_assertion_write_origin_census import analyze_corpus, enumerate_assertions


def corpus_for(source):
    index=Index({'case.py':source})
    module=index.paths['case.py']
    tests={}
    for node in module.tree.body:
        if isinstance(node,ast.FunctionDef) and node.name.startswith('test_'):
            span=module.span(node)
            identifier=f"case.py:{node.lineno}:{node.name}"
            tests[identifier]=dict(id=identifier,definition_span=span,support={'helpers':[]})
    return dict(sources={'case.py':{'code':source}},tests=tests,capsules=[])


LIB='''class Item:
    def __init__(self):
        self.ready = False
    def advance(self):
        self.ready = True
'''


def test_all_assertions_enumerated_with_one_index_and_same_line_disambiguation():
    c=corpus_for(LIB+'''\ndef test_a():
    item = Item()
    assert item.ready is False; assert not item.ready
    item.advance()
    assert item.ready
def test_b():
    assert 1 == 1
''')
    with patch('scripts.analyze_assertion_write_origin_census.Index',wraps=Index) as builder:
        result=analyze_corpus(c)
    assert builder.call_count==1
    assert result['summary']['unique_assertions']==4
    assert result['summary']['supported_partial_assertions']==3
    assert result['summary']['unsupported_assertions']==1
    ranked=sorted((r for r in result['assertions'] if r['supported_rank']),key=lambda r:r['supported_rank'])
    assert ranked[0]['retrieval']['tier']=='multiple_writers_and_prior_operation'
    assert ranked[0]['span']['line']==11
    same_line=[r for r in result['assertions'] if r['span']['line']==9]
    assert len(same_line)==2 and {r['analysis']['status'] for r in same_line}=={'partial'}


def test_existing_framework_capsule_and_explicit_helper_stay_in_scope():
    source=LIB+'''\ndef helper():
    item=Item()
    assert not item.ready
def test_a():
    helper()
    with pytest.raises(ValueError):
        broken()
'''
    c=corpus_for(source);index=Index(c['sources']);module=index.paths['case.py']
    helper=next(n for n in module.tree.body if isinstance(n,ast.FunctionDef) and n.name=='helper')
    owner=next(iter(c['tests']))
    c['tests'][owner]['support']['helpers']=[{'span':module.span(helper)}]
    raises=next(n for n in ast.walk(module.tree) if isinstance(n,ast.With))
    c['capsules']=[{'id':'framework_1','test_id':owner,'assertion_span':module.span(raises),'assertion':module.text(raises)}]
    result=analyze_corpus(c)
    assert result['summary']['unique_assertions']==2
    assert result['summary']['framework_or_non_assert_observations']==1
    assert result['summary']['supported_partial_assertions']==1
    assert result['summary']['unsupported_reason_occurrences']=={'framework_assertion_not_supported':1}
    helper_row=next(r for r in result['assertions'] if r['form']=='python_assert')
    assert 'referenced_helper' in helper_row['enumerated_from'] and helper_row['test_ids']==[owner]


def test_source_order_resolves_ties_but_tie_range_is_exposed():
    c=corpus_for(LIB+'''\ndef test_b():
    item=Item()
    item.advance()
    assert item.ready
def test_a():
    item=Item()
    item.advance()
    assert item.ready
''')
    result=analyze_corpus(c)
    assert all(r['evidence_tie_rank_range']==[1,2] for r in result['assertions'])
    assert all(r['evidence_tie_rank_range']==[1,2] for r in result['tests'])
    first=min(result['tests'],key=lambda r:r['supported_rank'])
    assert first['test_id'].endswith(':test_b')


def test_other_instance_operation_does_not_upgrade_observation_tier():
    c=corpus_for(LIB+'''\ndef test_a():
    a=Item()
    b=Item()
    a.advance()
    assert b.ready is False
''')
    result=analyze_corpus(c)
    q=result['assertions'][0]
    assert q['retrieval']['tier']=='bound_writer_only'
    assert q['retrieval']['reads'][0]['prior_same_binding_operation_has_syntactic_writer_path'] is False


def test_unrelated_sources_and_nonreferenced_helpers_not_claimed_as_test_assertions():
    c=corpus_for('''def unrelated():
    assert 1
def test_a():
    pass
''')
    result=analyze_corpus(c)
    assert result['summary']['unique_assertions']==0
    assert result['summary']['tests_without_enumerated_assertion']==1
    assert result['tests'][0]['supported_rank'] is None


def test_capsule_and_ast_assertion_are_counted_once():
    c=corpus_for('def test_a():\n    assert True\n')
    index=Index(c['sources']);module=index.paths['case.py'];node=next(n for n in ast.walk(module.tree) if isinstance(n,ast.Assert))
    c['capsules']=[{'id':'q','test_id':next(iter(c['tests'])),'assertion_span':module.span(node),'assertion':'assert True'}]
    rows,_=enumerate_assertions(c,index)
    assert len(rows)==1 and rows[0]['capsule_ids']==['q']


def test_capsule_from_unparseable_source_has_parse_reason_not_framework_reason():
    c=corpus_for('def test_a():\n    assert True\n')
    owner=next(iter(c['tests']))
    span={'path':'bad.py','line':2,'end_line':2,'start_byte':0,'end_byte':11}
    c['sources']['bad.py']={'code':'def invalid(\n    assert True\n'}
    c['capsules']=[{'id':'unparsed','test_id':owner,'assertion_span':span,'assertion':'assert True'}]
    result=analyze_corpus(c)
    row=next(q for q in result['assertions'] if q['capsule_ids']==['unparsed'])
    assert row['analysis']['reason']=='source_missing_or_unparseable'
    assert result['summary']['unparseable_source_assertions']==1
    assert result['summary']['framework_or_non_assert_observations']==0
