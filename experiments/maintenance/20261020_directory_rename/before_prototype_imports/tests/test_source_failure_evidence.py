import copy

import pytest

from anchor_retrieval.syntax import Source
from experimental.source_failure_evidence import analyze, analyze_corpus


PROGRAM = '''package assertions
import (
    tb "testing"
    "reflect"
)
// 源码位置 UTF-8.
func Compare(t *tb.T, a, b interface{}, note ...interface{}) {
    if a == nil { Absent(t, b, note...); return }
    Present(t, b, note...)
    SameType(t, a, b, note...)
    switch a := a.(type) {
    case int:
        if a != b.(int) { Emit(t, a, b, note...) }
    case string:
        if a != b.(string) { Emit(t, a, b, note...) }
    case []string:
        Sequence(t, a, b.([]string), note...)
    default:
        panic("unhandled type")
    }
}
func Absent(t *tb.T, v interface{}, note ...interface{}) {
    if !isNil(v) { Emit(t, nil, v, note...) }
}
func Present(t *tb.T, v interface{}, note ...interface{}) {
    if isNil(v) { Emit(t, "present", v, note...) }
}
func SameType(t *tb.T, a, b interface{}, note ...interface{}) {
    if reflect.TypeOf(a) != reflect.TypeOf(b) { Emit(t, a, b, note...) }
}
func Sequence(t *tb.T, a, b []string, note ...interface{}) {
    if len(a) != len(b) { Emit(t, a, b, note...); return }
    // Iteration semantics are deliberately outside this source prototype.
    for i := range a { Compare(t, a[i], b[i], note...) }
}
func Emit(t *tb.T, a, b interface{}, note ...interface{}) {
    t.Logf("diagnostics: %v %v %v", a, b, note)
    t.FailNow()
}
'''


def run(code=PROGRAM, path='pkg/assertions.go'):
    source = Source(path,code,'go')
    return source,analyze([source])


def function(result,name):
    return next(row for row in result['functions'] if row['name']==name)


def text(source,extent):
    return source.data[extent['start_byte']:extent['end_byte']].decode()


def test_cross_function_source_checks_reach_typed_sink_without_oracle_role_names():
    source,result=run()
    assert result['counts']['testing_sinks']==1
    assert all(row['can_reach_failure'] for row in result['functions'])
    assert function(result,'Compare')['condition_formal_dependencies']==['a','b']
    assert function(result,'Absent')['condition_formal_dependencies']==['v']
    assert function(result,'SameType')['condition_formal_dependencies']==['a','b']
    assert function(result,'Emit')['condition_formal_dependencies']==[]
    compare=function(result,'Compare')
    calls=[row for row in result['calls'] if row['id'] in compare['check_call_ids']]
    assert [row['callee'] for row in calls]==['Absent','Present','SameType','Emit','Emit','Sequence']
    assert not any(row['callee']=='panic' for row in calls)
    sink,=result['sinks']
    assert sink['receiver_formal']['type']=='*tb.T'
    assert sink['method']=='FailNow' and sink['diagnostic_arguments']==[]
    assert all(text(source,row['span'])==row['code'] for row in result['calls'])
    assert all(text(source,c['expression']['span'])==c['expression']['code'] for c in result['conditions'])


def test_grouped_fixed_formals_and_variadic_spread_remain_independently_bound():
    _,result=run()
    compare=function(result,'Compare')
    assert [p['name'] for p in compare['parameters']]==['t','a','b','note']
    call=next(row for row in result['calls'] if row['caller_id']==compare['id'] and row['callee']=='SameType')
    assert call['status']=='same_package_static_call'
    assert [b['formal']['name'] for b in call['actual_formal']]==['t','a','b','note']
    assert call['actual_formal'][-1]['actuals'][0]['code']=='note...'
    assert call['actual_formal'][-1]['actuals'][0]['formal_dependencies']==['note']
    check=next(row for row in result['checks'] if row['call_id']==call['id'])
    assert check['callee_condition_formal_dependencies']==['a','b']


def test_type_switch_shadow_binds_to_outer_formal_and_preserves_operand_spans():
    source,result=run()
    compare=function(result,'Compare')
    conditions=[c for c in result['conditions'] if c['function_id']==compare['id']]
    switch=next(c for c in conditions if c['form']=='type_switch_statement' and c['case_patterns'][0]['code']=='int')
    assert switch['formal_dependencies']==['a']
    branch=next(c for c in conditions if c['form']=='if' and c['expression']['code']=='a != b.(int)')
    assert branch['formal_dependencies']==['a','b']
    assert [p['formal_dependencies'] for p in branch['operands']]==[['a'],['b']]
    for operand in branch['operands']:
        assert text(source,operand['span'])==operand['code']


def test_arbitrary_function_and_formal_renaming_does_not_change_evidence_counts():
    renamed=PROGRAM
    for before,after in [('Compare','Unrelated'),('Emit','Zebra'),('SameType','Widget'),('Absent','First'),('Present','Second'),('Sequence','Third')]:
        renamed=renamed.replace(before,after)
    _,first=run();_,second=run(renamed)
    assert first['counts']==second['counts']
    assert function(second,'Unrelated')['condition_formal_dependencies']==['a','b']
    _,renamed_params=run('''package p
import "testing"
func Something(subject *testing.T, right, left int, text string){
    if right != left { End(subject,text) }
}
func End(subject *testing.T, text string){subject.Fatal(text)}
''')
    assert function(renamed_params,'Something')['condition_formal_dependencies']==['left','right']


@pytest.mark.parametrize('method,arguments',[('Fail',''),('FailNow',''),('Error','a'),('Errorf','"%v", a'),('Fatal','a'),('Fatalf','"%v", a')])
def test_only_standard_testing_failure_methods_are_source_sinks(method,arguments):
    _,result=run('package p\nimport "testing"\nfunc f(t *testing.T,a int){t.'+method+'('+arguments+')}')
    assert len(result['sinks'])==1
    assert function(result,'f')['condition_formal_dependencies']==[]
    assert len(result['sinks'][0]['diagnostic_arguments'])==(2 if method.endswith('f') else bool(arguments))


@pytest.mark.parametrize('declaration,imported', [
    ('*Fake','testing'),('interface{}','testing'),('*testing.T','example.com/testing'),
])
def test_fake_fail_object_or_nonstandard_testing_type_does_not_seed_reachability(declaration,imported):
    _,result=run('package p\nimport "'+imported+'"\ntype Fake struct{}\nfunc f(t '+declaration+') {t.FailNow()}')
    assert not result['sinks'] and not function(result,'f')['can_reach_failure']
    assert result['counts']['unknown_reasons']['testing_sink_receiver_type_unproved']==1


def test_testing_receiver_rebinding_and_static_callee_shadow_are_unknown():
    _,result=run('''package p
import "testing"
func f(t *testing.T){ t=other; t.FailNow() }
func g(t *testing.T){ f:=other; f(t) }
''')
    assert not result['sinks']
    assert result['counts']['unknown_reasons']=={'testing_sink_receiver_rebound':1,'callee_shadowed_or_reassigned':1}


@pytest.mark.parametrize('statement',[
    'for _,t := range xs {t.Fatal("msg")}',
    'if true {var a,t = 1,Other{};_=a;t.Fatal("msg")}',
])
def test_range_or_grouped_local_var_shadow_cannot_promote_fake_testing_sink(statement):
    _,result=run('package p\nimport "testing"\ntype Other struct{}\nfunc f(t *testing.T,xs []Other){'+statement+'}')
    assert not result['sinks'] and not function(result,'f')['can_reach_failure']
    reason='control_or_scheduling_unsupported' if statement.startswith('for') else 'testing_sink_receiver_rebound'
    assert result['counts']['unknown_reasons'][reason]==1


def test_local_type_alias_method_expression_is_not_the_testing_formal_receiver():
    _,result=run('''package p
import "testing"
type Other struct{}
func (Other) Fatal(string) {}
func f(t *testing.T){{type t = Other;t.Fatal(Other{},"msg")}}
''')
    assert not result['sinks'] and not function(result,'f')['can_reach_failure']
    assert result['counts']['unknown_reasons']['testing_sink_receiver_rebound']==1


def test_local_type_conversion_is_not_same_spelling_package_function_call():
    _,result=run('''package p
import "testing"
func Leaf(t *testing.T){t.Fatal("msg")}
func f(t *testing.T){type Leaf = *testing.T; _=Leaf(t)}
''')
    assert function(result,'Leaf')['can_reach_failure']
    assert not function(result,'f')['can_reach_failure']
    assert result['counts']['unknown_reasons']['callee_shadowed_or_reassigned']==1


def test_recursive_finite_graph_converges_and_projects_only_callee_guard_formals():
    _,result=run('''package p
import "testing"
func A(t *testing.T,p,q int,note string){B(t,q,p,note)}
func B(t *testing.T,x,y int,note string){if x!=y {t.Error(note)}; A(t,y,x,note)}
func Alone(t *testing.T){Alone(t)}
''')
    assert function(result,'A')['condition_formal_dependencies']==['p','q']
    assert function(result,'B')['condition_formal_dependencies']==['x','y']
    assert function(result,'A')['can_reach_failure'] and function(result,'B')['can_reach_failure']
    assert not function(result,'Alone')['can_reach_failure']
    assert result['counts']['reachability_iterations']<=3
    assert result['counts']['dependency_iterations']<=3


def test_same_package_resolution_requires_unique_directory_and_declaration():
    left=Source('one/a.go','package p\nimport "testing"\nfunc f(t *testing.T){g(t)}','go')
    right=Source('two/b.go','package p\nimport "testing"\nfunc g(t *testing.T){t.Fail()}','go')
    result=analyze([left,right])
    assert not function(result,'f')['can_reach_failure']
    same=Source('one/b.go',right.code,'go')
    assert function(analyze([left,same]),'f')['can_reach_failure']
    duplicate=Source('one/c.go',right.code,'go')
    ambiguous=analyze([left,same,duplicate])
    assert not function(ambiguous,'f')['can_reach_failure']
    assert ambiguous['counts']['unknown_reasons']['same_package_function_ambiguous']==1
    assert analyze([left,same])==analyze([same,left])


def test_only_failure_conditions_not_log_payloads_enter_transitive_dependencies():
    _,result=run('''package p
import "testing"
func Entry(t *testing.T,value int,payload string){nested(t,value*2,payload)}
func nested(t *testing.T,x int,payload string){if x<0 {finish(t,payload)}}
func finish(t *testing.T,payload string){t.Logf("%s",payload);t.Error(payload)}
''')
    assert function(result,'Entry')['condition_formal_dependencies']==['value']
    assert function(result,'nested')['condition_formal_dependencies']==['x']
    assert function(result,'finish')['condition_formal_dependencies']==[]


def test_if_initializer_and_else_polarity_are_retained_as_source_facts():
    _,result=run('''package p
import "testing"
func f(t *testing.T,x,y int){if z:=x+1;z==y { return } else {t.FailNow()}}
''')
    condition,=result['conditions']
    assert condition['polarity']=='false'
    assert condition['expression']['code']=='z==y'
    assert condition['formal_dependencies']==['x','y']


@pytest.mark.parametrize('prefix',[
    'if a:=b; a<0 {t.Error("first")};',
    '{a:=b;_=a};',
    'if true {a:=b;_=a};',
    'switch a:=b; a {case 1: t.Error("first")};',
])
def test_control_and_block_short_shadow_does_not_escape_its_source_scope(prefix):
    _,result=run('package p\nimport "testing"\nfunc f(t *testing.T,a,b int){'+prefix+'if a<0{t.Error("second")}}')
    second=next(row for row in result['checks'] if 'second' in row['code'])
    guard=next(row for row in result['conditions'] if row['check_call_id']==second['call_id'])
    assert guard['formal_dependencies']==['a']


def test_initializer_assignment_persists_and_parallel_assignment_uses_old_values():
    _,result=run('''package p
import "testing"
func f(t *testing.T,a,b int){if a=b;a<0 {t.Error("first")};if a<0{t.Error("second")}}
func g(t *testing.T,a,b int){a,b=b,a;if b<0{t.Fail()}}
func h(t *testing.T,a,b int){var x,y=a,b;if y<0{t.Fail()}}
''')
    second=next(row for row in result['checks'] if 'second' in row['code'])
    assert next(row for row in result['conditions'] if row['check_call_id']==second['call_id'])['formal_dependencies']==['b']
    assert function(result,'g')['condition_formal_dependencies']==['a']
    assert function(result,'h')['condition_formal_dependencies']==['b']


def test_unsupported_loop_does_not_bind_outer_formal_to_a_shadowed_iterator():
    _,result=run('''package p
import "testing"
func f(t *testing.T,x int,values []int){for _,x:=range values{leaf(t,x)}}
func leaf(t *testing.T,x int){if x<0{t.FailNow()}}
''')
    assert function(result,'f')['status']=='partial_unknown'
    assert not function(result,'f')['can_reach_failure']
    assert not any(row['caller_id']==function(result,'f')['id'] for row in result['calls'])


def test_local_function_body_and_other_languages_are_explicitly_unsupported():
    _,result=run('package p\nimport "testing"\nfunc f(t *testing.T){g:=func(){t.FailNow()};g()}')
    assert not result['sinks'] and not function(result,'f')['can_reach_failure']
    assert result['counts']['unknown_reasons']['nested_function_body_unsupported']==1
    other=analyze([Source('test_x.py','def test_x():\n    assert False\n','python')])
    assert not other['functions'] and other['unknowns'][0]['reason']=='language_unsupported'


def test_bodyless_external_declaration_is_unknown_without_crashing_inventory():
    _,result=run('package p\nimport "testing"\nfunc external(t *testing.T)')
    assert function(result,'external')['reason']=='function_body_unavailable'
    assert not function(result,'external')['can_reach_failure']


def test_corpus_entry_does_not_mutate_inputs():
    corpus=dict(language='go',sources={'pkg/check.go':dict(code=PROGRAM)})
    original=copy.deepcopy(corpus)
    result=analyze_corpus(corpus)
    assert corpus==original and result['counts']['testing_sinks']==1
