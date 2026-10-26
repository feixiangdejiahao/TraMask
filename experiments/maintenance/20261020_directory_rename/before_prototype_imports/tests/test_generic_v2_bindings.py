"""Source-only examples for the experimental lexical and callable checker."""
import pytest

from experimental.generic_v2.bindings import analyze_bindings


def check(code, before, after, language='python', **kwargs):
    start = code.encode().index(before.encode())
    return analyze_bindings(code, language, start, after,
                            end_byte=start + len(before.encode()), **kwargs)


def reasons(result):
    return {r['reason'] for r in result['errors']}


def binding(result, name):
    return next(r for r in result['bindings'] if r['name'] == name)


def test_python_visible_parameter_local_outer_global_and_import():
    code = '''import math as m
GLOBAL = 7
def helper(x):
    return x
def outer(outer_arg):
    outer_local = 2
    def inner(local_arg):
        own = 3
        return local_arg
    return inner
'''
    r = check(code, 'return local_arg', 'return helper(local_arg + own + outer_local + outer_arg + GLOBAL) + m.pi')
    assert not r['errors']
    assert all(binding(r, n)['status'] == 'available' for n in ['helper', 'local_arg', 'own', 'outer_local', 'outer_arg', 'GLOBAL', 'm'])
    assert binding(r, 'outer_arg')['binding_id'] != binding(r, 'local_arg')['binding_id']
    assert 'pi' not in {n['name'] for n in r['bindings']}


def test_python_later_local_is_unbound_even_with_outer_same_name():
    r = check('x=3\ndef test():\n    a=0\n    x=4\n    return a\n', 'a=0', 'a=x')
    assert 'use_before_local_definition' in reasons(r)
    assert binding(r, 'x')['binding_kind'] == 'local'


def test_python_sibling_local_does_not_become_available():
    r = check('def sibling():\n secret=3\ndef test():\n return 0\n', 'return 0', 'return secret')
    assert binding(r, 'secret')['status'] == 'unknown'
    assert binding(r, 'secret')['binding_id'] is None
    assert not r['errors']


def test_python_class_namespace_not_visible_from_method():
    code = 'class Box:\n    value=3\n    def method(self):\n        return 0\n'
    r = check(code, 'return 0', 'return value')
    assert binding(r, 'value')['status'] == 'unknown'


def test_python_conditional_local_and_delayed_closure_are_unknown():
    code = 'def test(flag):\n if flag:\n  x=1\n def inner():\n  return 0\n late=2\n return x\n'
    r = check(code, 'return 0', 'return late+x')
    assert not r['errors']
    assert binding(r, 'late')['status'] == 'unknown'
    assert binding(r, 'x')['status'] == 'unknown'


@pytest.mark.parametrize('after,error', [
    ('f(1)', 'missing_required_arguments'),
    ('f(1,2,3,flag=True)', 'too_many_positional_arguments'),
    ('f(1,a=2,flag=True)', 'multiple_values_for_argument'),
    ('f(1,flag=True,other=2)', 'unexpected_keyword_argument'),
])
def test_python_explicit_signature_rejects_known_wrong_arity(after, error):
    code = 'def f(a,b=2,*,flag):\n return a\ndef test():\n return f(1,flag=True)\n'
    assert error in reasons(check(code, 'f(1,flag=True)', after))


def test_python_defaults_keywords_and_variadics_stay_valid():
    code = 'def f(a,/,b=2,*xs,flag,**kw):\n return a\ndef test():\n return f(1,flag=True)\n'
    r = check(code, 'f(1,flag=True)', 'f(1,2,3,flag=True,a=4,other=5)')
    assert r['status'] == 'compatible'


def test_python_unknown_spread_and_decorated_signature_not_rejected():
    code = '@factory\ndef f(a):\n return a\ndef test(args):\n return f(1)\n'
    r = check(code, 'f(1)', 'f(*args,extra=2)')
    assert r['status'] == 'unknown' and not r['errors']


def test_python_tuple_return_is_one_value_not_go_multiple_results():
    code = 'def pair():\n return (1,2)\ndef one(x):\n return x\ndef test():\n return one(1)\n'
    r = check(code, 'one(1)', 'one(pair())')
    assert r['status'] == 'compatible'
    assert all(c['signature']['return_count'] == 1 for c in r['calls'])


def test_primitive_callee_rejected_but_unknown_function_transform_allowed():
    code = 'def test(fn):\n x=3\n return fn(1)\n'
    assert 'known_noncallable_value' in reasons(check(code, 'fn(1)', 'x(1)'))
    r = check(code, 'fn(1)', 'fn(fn(1))')
    assert r['status'] == 'unknown' and not r['errors']


def test_lambda_binders_are_local_and_callable_signature_is_used():
    code = 'def test():\n return 1\n'
    r = check(code, 'return 1', 'return (lambda x: x + 1)(2)')
    assert r['status'] == 'compatible'
    assert binding(r, 'x')['binding_kind'] == 'parameter'
    bad = check(code, 'return 1', 'return (lambda x: x + 1)(2,3)')
    assert 'too_many_positional_arguments' in reasons(bad)


def test_ts_scope_shadowing_and_td_z():
    code = 'const x=1; function test(){ { const y=2; } const z=0; const x=3; return z; }'
    r = check(code, 'z=0', 'z=x+y', 'typescript')
    assert 'use_before_local_definition' in reasons(r)
    assert binding(r, 'y')['status'] == 'unknown'
    assert binding(r, 'x')['binding_kind'] == 'local'


def test_ts_var_scope_is_function_wide_but_initialization_is_unknown():
    code = 'function test(){ const x=0; if(true){var late=1;} return x; }'
    r = check(code, 'x=0', 'x=late', 'typescript')
    assert binding(r, 'late')['status'] == 'unknown'
    assert not r['errors']


def test_ts_default_namespace_and_named_imports_available():
    code = 'import d, {foo as f} from "lib"; import * as ns from "other"; function test(){ return 1; }'
    r = check(code, 'return 1', 'return d(f(ns.value))', 'typescript')
    assert all(binding(r, n)['status'] == 'available' for n in ['d', 'f', 'ns'])
    assert r['status'] == 'unknown' and not r['errors']


def test_ts_arrows_optional_defaults_and_rest_signatures():
    code = 'const f=(a:number,b?:number,...xs:number[])=>a; function test(){return f(1);}'
    assert check(code, 'f(1)', 'f(1,2,3,4)', 'typescript')['status'] == 'compatible'
    assert 'missing_required_arguments' in reasons(check(code, 'f(1)', 'f()', 'typescript'))


def test_unknown_receiver_never_borrows_same_named_method():
    code = 'class A { run(x:number){ return x; } } function test(other:any){return other.run(1);}'
    r = check(code, 'other.run(1)', 'other.run(1,2,3)', 'typescript')
    assert r['status'] == 'unknown' and not r['errors']
    assert r['calls'][0]['signature'] is None


def test_go_later_local_does_not_shadow_prior_outer_until_declaration():
    code = 'package p\nvar x=3\nfunc test(){ y:=0; x:=4; _=x; _=y }'
    r = check(code, 'y:=0', 'y:=x', 'go')
    assert not r['errors']
    assert ':module@' in binding(r, 'x')['binding_id']


def test_go_loop_and_if_initializer_scope():
    code = 'package p\nfunc id(a int)int{return a}\nfunc test(){if x:=id(1);x>0{y:=0;_=y}; z:=0;_=z}'
    within = check(code, 'y:=0', 'y:=id(x)', 'go')
    assert within['status'] == 'compatible'
    outside = check(code, 'z:=0', 'z:=id(x)', 'go')
    assert binding(outside, 'x')['status'] == 'unknown'
    assert not outside['errors']


def test_go_grouped_parameters_variadic_and_return_count():
    code = 'package p\nfunc pair(a,b int,rest ...string)(int,error){return a,nil}\nfunc test(){x,e:=pair(1,2);_=x;_=e}'
    good = check(code, 'pair(1,2)', 'pair(1,2,"a","b")', 'go')
    assert good['status'] == 'compatible'
    assert good['calls'][0]['signature']['return_count'] == 2
    assert 'missing_required_arguments' in reasons(check(code, 'pair(1,2)', 'pair(1)', 'go'))
    bad = check(code, 'x,e:=pair(1,2)', 'x:=pair(1,2)', 'go')
    assert 'return_count_mismatch' in reasons(bad)


def test_go_multivalue_call_expands_only_as_sole_argument():
    code = 'package p\nfunc pair()(int,int){return 1,2}\nfunc add(a,b int)int{return a+b}\nfunc test(){x:=add(1,2);_=x}'
    assert check(code, 'add(1,2)', 'add(pair())', 'go')['status'] == 'compatible'
    assert 'return_count_mismatch' in reasons(check(code, 'add(1,2)', 'add(1,pair())', 'go'))


def test_go_function_literal_binds_parameter_and_known_arity():
    code = 'package p\nfunc test(){x:=0;_=x}'
    r = check(code, 'x:=0', 'x:=(func(a int)int{return a})(2)', 'go')
    assert r['status'] == 'compatible'
    assert binding(r, 'a')['binding_kind'] == 'parameter'


def test_unicode_byte_span_and_no_source_mutation():
    code = 'def f(x):\n return x\ndef test():\n label="你好"\n return f(1)\n'
    r = check(code, 'f(1)', 'f(label)')
    assert r['status'] == 'compatible'
    assert r['bindings'][0]['span']['start_byte'] == code.encode().index(b'f(1)')
    assert 'f(label)' not in code


def test_added_import_available_but_signature_unknown():
    r = check('def test():\n return 0\n', 'return 0', 'return injected(1)', imported_names=['injected'])
    assert binding(r, 'injected')['reason'] == 'validated_import_addition'
    assert r['status'] == 'unknown' and not r['errors']


def test_only_introduced_syntax_errors_are_rejections():
    code = 'def test():\n return 1\n'
    assert 'introduced_syntax_error' in reasons(check(code, 'return 1', 'return f('))
    code = 'const broken = ; function test(){return 1;}'
    r = check(code, 'return 1', 'return 2', 'typescript')
    assert r['baseline_parse_errors'] > 0
    assert not r['errors']


def test_unedited_unknown_and_invalid_calls_elsewhere_not_checked():
    code = 'def f(x):\n return x\ndef unrelated():\n return f(1,2,3)\ndef test():\n return f(1)\n'
    assert check(code, 'return f(1)\n', 'return f(2)\n')['status'] == 'compatible'


@pytest.mark.parametrize('language,code,before,after', [
    ('python', 'def test():\n for x in [1]:\n  print(0)\n', 'print(0)', 'print(x)'),
    ('python', 'def test():\n return [x for x in [1]]\n', '[x for x in [1]]', '[x+1 for x in [1]]'),
    ('python', 'f=1\ndef test():\n return 0\nf=lambda x:x\n', 'return 0', 'return f(1)'),
    ('python', 'def f(a):\n return a\ndef test():\n return 0\nf=lambda a,b:a\n', 'return 0', 'return f(1,2)'),
    ('python', 'def outer():\n x=1\n def inner():\n  return 0\n x=lambda a:a\n return inner\n', 'return 0', 'return x(2)'),
    ('typescript', 'function f(a:number,b:number):number; function f(a:number){return a;} function test(){return f(1);}', 'return f(1)', 'return f(1,2)'),
    ('typescript', 'function test(flag:boolean){let f=(a:number)=>a; if(flag){f=(a:number,b?:number)=>a;} return f(1);}', 'return f(1)', 'return f(1,2)'),
])
def test_execution_order_and_overloads_not_treated_as_definite_errors(language, code, before, after):
    r = check(code, before, after, language)
    assert not r['errors']
    assert r['status'] == 'unknown'


@pytest.mark.parametrize('language,code,before,after', [
    ('go', 'package p\nfunc test(f func(int,int)(string,error)){f(1,2)}', 'f(1,2)', 'f(1)'),
    ('typescript', 'function test(f:(x:number,y?:number)=>number){return f(1)}', 'f(1)', 'f(1,2,3)'),
])
def test_explicit_function_typed_parameter_has_known_signature(language, code, before, after):
    r = check(code, before, after, language)
    assert r['status'] == 'invalid'
    assert r['calls'][0]['signature'] is not None


def test_python_module_function_is_not_hoisted_at_module_execution():
    r = check('value=0\ndef later():\n return 1\n', 'value=0', 'value=later()')
    assert 'use_before_local_definition' in reasons(r)


def test_python_augmented_assignment_still_makes_a_name_local():
    code = 'x=1\ndef test():\n value=0\n x+=1\n return value\n'
    assert 'use_before_local_definition' in reasons(check(code, 'value=0', 'value=x'))


def test_ts_catch_parameter_and_destructuring_default_expression():
    code = 'function test(obj:any){try{}catch(err){return 0;}}'
    r = check(code, 'return 0', 'return err', 'typescript')
    assert binding(r, 'err')['status'] == 'available'
    code = 'function test(obj:any, fallback:any){const {x=fallback}=obj; return 0;}'
    r = check(code, 'return 0', 'return x', 'typescript')
    assert binding(r, 'x')['status'] == 'available'
