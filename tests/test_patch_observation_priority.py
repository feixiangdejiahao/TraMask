"""Source transport and finite patch-path scheduling; no subjects are executed."""
import copy
import difflib

import pytest

from anchor_retrieval.syntax import Source
from prototypes.patch_observation_priority import Analyzer, select
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.semantic_selection import select as baseline


def fixture(old='def compute(value):\n    return value * 2\n',
            new='def compute(value):\n    return value * 3\n',
            body='value = 11\nresult = compute(value)\nassert result == 22', language='python'):
    if language=='python':
        lib='library.py';test='test_source.py'
        text='from library import compute\ndef test_case():\n'+''.join('    '+row+'\n' for row in body.splitlines())
    elif language=='go':
        lib='library.go';test='source_test.go';text=body
    else:
        lib='library.ts';test='source.test.ts';text=body
    patch=''.join(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),fromfile='a/'+lib,tofile='b/'+lib,n=0))
    front=extract_frontend([Source(lib,new,language),Source(test,text,language)],patch=patch)
    return to_emitter_corpus(front),front,patch


def candidate(corpus,before='11',after='19',identifier='change',occurrence=0):
    base=next(iter(corpus['tests']));where=corpus['tests'][base]['span'];raw=corpus['sources'][where['path']]['code'].encode()
    start=where['start_byte']
    for i in range(occurrence+1):
        start=raw.index(before.encode(),start)
        if i<occurrence:start+=len(before.encode())
    return dict(id=identifier,base_test_id=base,operator='input',imports=[],edits=[dict(
        span=dict(path=where['path'],start_byte=start,end_byte=start+len(before.encode())),before=before,after=after,role='input')])


def evidence(c,f,p,row,mode='strict'):
    return select(c,f,[row],p,mode=mode)['ranking'][0]['evidence']


def test_exact_source_chain_has_patch_and_both_edit_coordinate_systems():
    c,f,p=fixture();row=candidate(c);frozen=copy.deepcopy((c,f,row))
    facts=evidence(c,f,p,row)
    assert facts['strong_priority'] and facts['may_priority']
    witness=facts['witnesses'][0]
    assert witness['original_edit_span']==row['edits'][0]['span']
    assert witness['patch_span']['path']=='library.py'
    assert 'value * 3' in witness['patch_code']
    assert (c,f,row)==frozen


def test_multibyte_insertion_transports_unchanged_original_assertion_bytes():
    c,f,p=fixture();row=candidate(c)
    added=candidate(c,'value = 11','value = 11')['edits'][0]
    added.update(before='',after='label = "雪"\n    ');added['span']['end_byte']=added['span']['start_byte']
    row['edits'].insert(0,added)
    facts=evidence(c,f,p,row);w=facts['witnesses'][0]
    assert facts['strong_priority']
    assert w['modified_assertion_span']['start_byte']-w['original_assertion_span']['start_byte']==len(added['after'].encode())


@pytest.mark.parametrize('mode',['strict','may'])
def test_deletion_only_patch_has_no_new_source_seed(mode):
    old='def compute(value):\n    ignored = 99\n    return value\n';new=old.replace('    ignored = 99\n','')
    c,f,p=fixture(old,new);facts=evidence(c,f,p,candidate(c),mode)
    assert not facts['strong_priority'] and not facts['may_priority']
    assert any('deletion' in row['reason'] or 'deleted' in row['reason'] for row in facts['patch_unknowns'])


def test_changed_diagnostic_on_same_physical_line_does_not_patch_unchanged_return():
    old='def compute(value): note = "old"; return value\n';new=old.replace('"old"','"new"')
    c,f,p=fixture(old,new);facts=evidence(c,f,p,candidate(c))
    assert not facts['strong_priority'] and facts['may_priority']


def test_patch_new_line_mismatch_is_explicit_unknown():
    c,f,p=fixture();p=p.replace('return value * 3','return value * 99')
    facts=evidence(c,f,p,candidate(c))
    assert not facts['strong_priority'] and not facts['may_priority']
    assert 'patch_new_line_source_mismatch' in {r['reason'] for r in facts['patch_unknowns']}


def test_no_path_retains_complete_original_fair_ranking_and_budget_prefix():
    c,f,p=fixture();rows=[candidate(c,identifier=str(i),after=str(30+i)) for i in range(8)]
    expected=baseline(c,rows,budget=2)
    for mode in ('strict','may'):
        result=select(c,f,rows,'',budget=2,mode=mode)
        assert [r['id'] for r in result['ranking']]==[r['id'] for r in expected['ranking']]
        assert len(result['ranking'])==8 and len(result['selected'])==2


def test_two_level_source_return_path_projects_input_through_same_call_instances():
    old='def compute(value):\n    return nested(value + 1)\ndef nested(number):\n    return number * 2\n'
    new=old.replace('* 2','* 3');c,f,p=fixture(old,new)
    facts=evidence(c,f,p,candidate(c))
    assert facts['strong_priority']
    assert len(facts['witnesses'][0]['call_chain'])==2


def test_original_import_reassignment_does_not_reuse_original_callee():
    c,f,p=fixture(body='value = 11\ncompute = unknown\nresult = compute(value)\nassert result == 22')
    facts=evidence(c,f,p,candidate(c),'may')
    assert not facts['strong_priority'] and not facts['may_priority']
    assert 'callee_unresolved_or_ambiguous' in facts['unknowns']


@pytest.mark.parametrize('language,old,new,body',[
 ('go','package sample\nfunc compute(value int) int {return value * 2}\n','package sample\nfunc compute(value int) int {return value * 3}\n',
  'package sample\nimport "testing"\nfunc TestCase(t *testing.T){value:=11;result:=compute(value);if result!=22{t.Error(result)}}\n'),
 ('typescript','export function compute(value: number): number {return value * 2;}\n','export function compute(value: number): number {return value * 3;}\n',
  'import {compute} from "./library";\ntest("case",()=>{let value=11;let result=compute(value);expect(result).toBe(22);});\n')])
def test_go_and_typescript_core_return_binding(language,old,new,body):
    c,f,p=fixture(old,new,body,language);facts=evidence(c,f,p,candidate(c))
    assert facts['strong_priority'],facts['unknowns']


def test_representative_material_is_bounded_and_may_cache_reuses_immutable_source():
    old='def compute(value):\n    return value * 2\n';new='def compute(value):\n    first = value + 1\n    second = first + 2\n    return second * 3\n'
    c,f,p=fixture(old,new);analyzer=Analyzer(c,f,p)
    a=analyzer.evidence(candidate(c,identifier='a'));count=len(analyzer.may_cache)
    b=analyzer.evidence(candidate(c,identifier='b',after='20'))
    assert a['strong_priority'] and b['strong_priority']
    assert len(a['witnesses'])==len(a['may_witnesses'])==1
    assert len(analyzer.may_cache)==count


def test_go_receiver_type_declaration_is_not_a_module_rebinding():
    old='package sample\ntype Box struct{}\nfunc (b Box) Read(value int) int {return value * 2}\n'
    new=old.replace('* 2','* 3')
    body='package sample\nimport "testing"\nfunc TestCase(t *testing.T){b:=Box{};value:=11;result:=b.Read(value);if result!=22{t.Error(result)}}\n'
    c,f,p=fixture(old,new,body,'go');facts=evidence(c,f,p,candidate(c),'may')
    assert facts['may_priority'],facts['unknowns']
    assert 'target_module_binding_rebound_unknown' not in facts['unknowns']


@pytest.mark.parametrize('mode',['unknown',None])
def test_invalid_mode_is_rejected(mode):
    c,f,p=fixture()
    with pytest.raises(ValueError):select(c,f,[candidate(c)],p,mode=mode)
