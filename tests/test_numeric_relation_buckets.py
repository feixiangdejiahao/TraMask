import copy
from decimal import Decimal
from pathlib import Path

import pytest

from experimental.numeric_relation_buckets import candidate_relations, numeric_literal, refine_selections


SELECTOR=Path(__file__).resolve().parents[1]/'relation_search/semantic_selection.py'


def inputs(language='python',values=('4','100'),old='5',source=None):
    code=source or {'python':'def test_case():\n    use(5, 10)\n',
                   'go':'package x\nfunc TestCase(){use(5,10)}',
                   'typescript':'test("case",()=>{use(5,10);});'}[language]
    path={'python':'test_case.py','go':'case_test.go','typescript':'case.test.ts'}[language]
    start=code.index(old)
    corpus={'language':language,'sources':{path:{'code':code}},'tests':{'seed':{'retrieval_rank':1}}}
    candidates=[{'id':f'candidate_{i}','operator':'value_edit','base_test_id':'seed',
                 'edits':[{'span':{'path':path,'start_byte':start,'end_byte':start+len(old)},'before':old,'after':value}]} for i,value in enumerate(values)]
    return corpus,candidates


@pytest.mark.parametrize('language',['python','go','typescript'])
def test_smaller_larger_partitions_change_shape_but_not_candidate_material(language):
    corpus,candidates=inputs(language);original=copy.deepcopy((corpus,candidates))
    result=refine_selections(corpus,candidates,SELECTOR)
    assert result['selections']['baseline']['shape_count']==1
    assert result['selections']['delta']['shape_count']==2
    assert {row['delta_order'] for e in result['evidence'].values() for row in e}=={-1,1}
    assert (corpus,candidates)==original
    for arm in ('delta','context'):
        assert {r['content_sha256'] for r in result['selections'][arm]['ranking']}=={r['content_sha256'] for r in result['selections']['baseline']['ranking']}


def test_same_direction_remains_one_bucket_until_crossing_other_argument():
    corpus,candidates=inputs(values=('6','100'))
    result=refine_selections(corpus,candidates,SELECTOR)
    assert result['selections']['delta']['shape_count']==1
    assert result['selections']['context']['shape_count']==2
    for rows in result['evidence'].values():
        assert rows[0]['context'][0]['origin']=='input_syntax_only'


def test_local_read_has_explicit_assignment_and_comparison_source_spans():
    corpus,candidates=inputs(values=('6','100'),source='def test_case():\n    count = 5\n    assert count < 10\n')
    result=refine_selections(corpus,candidates,SELECTOR)
    assert result['selections']['delta']['shape_count']==1
    assert result['selections']['context']['shape_count']==2
    for rows in result['evidence'].values():
        relation=rows[0]['context'][0]
        assert relation['origin']=='local_test_def_use'
        assert relation['write_span']['line']==2 and relation['read_span']['line']==3


def test_reassignment_or_closure_write_does_not_make_fake_def_use_link():
    for code in ('def test_case():\n    count = 5\n    count = other\n    assert count < 10\n',
                 'def test_case():\n    count = 5\n    def update():\n        nonlocal count\n        count = 7\n    assert count < 10\n'):
        corpus,candidates=inputs(source=code)
        assert all(not row['context'] for row in candidate_relations(corpus,candidates[0]))


def test_renamed_local_bindings_keep_relation_signatures():
    results=[]
    for name in ('count','renamed'):
        corpus,candidates=inputs(values=('100',),source=f'def test_case():\n    {name} = 5\n    assert {name} < 10\n')
        results.append(refine_selections(corpus,candidates,SELECTOR)['selections']['context']['ranking'][0]['shape_id'])
    assert results[0]==results[1]


def test_digit_inside_string_is_not_a_numeric_ast_edit():
    corpus,candidates=inputs(source='def test_case():\n    use("5")\n')
    assert candidate_relations(corpus,candidates[0])==[]


@pytest.mark.parametrize('token',['True','false','"5"','0xZZ','001','NaN','Infinity','call()','5+1'])
def test_unsupported_numeric_text(token):
    assert numeric_literal(token) is None


@pytest.mark.parametrize('token,value',[('-2',-2),('0x10',16),('1_000',1000),('.5',Decimal('.5')),('1e3',1000)])
def test_supported_exact_mathematical_literals(token,value):
    assert numeric_literal(token)==value


def test_simultaneous_other_argument_edit_uses_changed_value():
    corpus,candidates=inputs(values=('6',))
    candidate=candidates[0];code=next(iter(corpus['sources'].values()))['code'];path=next(iter(corpus['sources']))
    start=code.index('10');candidate['edits'].append({'span':{'path':path,'start_byte':start,'end_byte':start+2},'before':'10','after':'1'})
    evidence=candidate_relations(corpus,candidate)
    first=evidence[0]['context'][0]
    assert first['signature']['before']==-1 and first['signature']['after']==1


def test_no_numeric_evidence_preserves_entire_schedule_and_target_annotations_ignored():
    corpus,candidates=inputs(old='5',values=('some_call()','other_call()'))
    candidates[0]['evaluation']={'target':True};candidates[1]['oracle_cache']={'hit':True}
    result=refine_selections(corpus,candidates,SELECTOR)
    assert not any(result['evidence'].values())
    rankings=[[r['id'] for r in arm['ranking']] for arm in result['selections'].values()]
    assert rankings[0]==rankings[1]==rankings[2]
