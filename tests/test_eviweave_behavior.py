"""Behavior facts checked against real parsers and executable counterexamples."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph


def index(code, suffix='.py'):
    graph = SourceGraph({'id': 'example', 'path': 'example' + suffix, 'raw': code.encode()})
    assert not graph.issues
    return BehaviorIndex(graph)


def calls(behavior, name):
    return [op for op in behavior.operations if op['kind'] == 'call' and op['name'] == name]


def run_python(code):
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('suffix,code', [
    ('.py', 'def f(x):\n if x:\n  return 1\n elif x == 2:\n  return 2\n else:\n  return 3\n impossible()\n'),
    ('.js', 'function f(x) { if(x) return 1; else return 2; impossible(); }'),
    ('.ts', 'function f(x: boolean) { if(x) return 1; else return 2; impossible(); }'),
    ('.go', 'package p\nfunc f(x bool) { if x { return } else if !x { return } else { return }; impossible() }'),
    ('.rs', 'fn f(x: bool) { if x { return; } else { return; } impossible(); }'),
])
def test_exhaustive_early_exit_has_no_fallthrough(suffix, code):
    behavior = index(code, suffix)
    operation = calls(behavior, 'impossible')[0]
    assert operation['reachability'] == 'unreachable_within_frame'
    assert behavior.graph.nodes[operation['statement']]['pred'] == set()


def test_early_exit_analysis_agrees_with_execution_and_missing_else_keeps_path():
    code = '''events = []
def impossible():
    events.append('impossible')
def f(x):
    if x:
        return 1
    else:
        return 2
    impossible()
def g(x):
    if x:
        return 1
    events.append('fallthrough')
f(True)
f(False)
g(False)
'''
    assert run_python(code + '\nimport json; print(json.dumps(events))') == ['fallthrough']
    behavior = index(code)
    assert calls(behavior, 'impossible')[0]['reachability'] == 'unreachable_within_frame'
    assert calls(behavior, 'append')[-1]['reachability'] == 'reachable_within_frame'


@pytest.mark.parametrize('suffix,code,inner_name,outer_name', [
    ('.py', 'def f(r, body):\n result = list(r.consume(body, mode="stream"))\n', 'consume', 'list'),
    ('.js', 'function f(r, body) { const result = collect(r.consume(body)); }', 'consume', 'collect'),
    ('.ts', 'function f(r: Client, body: string) { const result = collect(r.consume(body)); }', 'consume', 'collect'),
    ('.go', 'package p\nfunc f(r Client, body string) { result := collect(r.Consume(body)); _ = result }', 'Consume', 'collect'),
    ('.rs', 'fn f(r: Client, body: String) { let result = collect(r.consume(body)); }', 'consume', 'collect'),
])
def test_expression_ports_keep_nested_producer_consumer_and_result(suffix, code, inner_name, outer_name):
    behavior = index(code, suffix)
    inner, outer = calls(behavior, inner_name)[0], calls(behavior, outer_name)[0]
    assert inner['statement'] == outer['statement']
    assert inner['id'] != outer['id']
    assert inner['receiver']['text'] == 'r'
    assert inner['arguments'][0]['role'] == 'positional:0'
    assert inner['arguments'][0]['text'] == 'body'
    assert inner['id'] in outer['arguments'][0]['producer_operations']
    assert outer['result']['definitions']
    assert {'before': inner['id'], 'after': outer['id'], 'kind': 'operand_evaluation',
            'condition': 'both_events_reached_in_same_activation'} in behavior.order
    if suffix == '.py':
        assert inner['arguments'][1]['role'] == 'keyword:mode'


def test_rebinding_keeps_direct_identity_without_promoting_may_alias():
    code = 'a=[]\nb=a\na=[]\na.append(1)\nassert not b\n'
    assert run_python(code + '\nimport json; print(json.dumps([a, b, a is b]))') == [[1], [], False]
    behavior = index(code)
    first_a, b, second_a = behavior.definitions
    assert b['value_identity'] == first_a['value_identity']
    assert second_a['value_identity'] != first_a['value_identity']
    append = calls(behavior, 'append')[0]
    observation = next(op for op in behavior.operations if op['kind'] == 'assert')
    observed_b = observation['arguments'][0]['reads'][0]
    assert append['receiver']['value_identity'] == second_a['value_identity']
    assert observed_b['value_identity'] == first_a['value_identity']
    assert behavior.graph.nodes[observation['statement']]['state']  # May state was deliberately retained.


def test_augmented_assignment_does_not_copy_right_operand_identity():
    setup = 'a=[]\nb=[]\na += b\n'
    assert run_python(setup + 'import json; print(json.dumps(a is b))') is False
    behavior = index(setup + 'consume(a, b)\n')
    left, right = calls(behavior, 'consume')[0]['arguments']
    assert left['value_identity'] is None
    assert right['identity_kind'] == 'fresh_allocation'
    assignment = behavior.definitions[-1]
    assert assignment['value_kind'] == 'unresolved'
    assert 'augmented_assignment_result_identity' in assignment['unknowns']


@pytest.mark.parametrize('suffix,code', [
    ('.py', 'a=[]\nconsume((a := fresh_value()))\n'),
    ('.js', 'let a=[]; consume(a = fresh_value());'),
])
def test_assignment_target_is_not_an_old_value_read(suffix, code):
    from eviweave.relations import RelationIndex
    behavior = index(code, suffix)
    consume = calls(behavior, 'consume')[0]
    assert all(read['text'] != 'a' for read in consume['arguments'][0]['reads'])
    relations = RelationIndex(behavior.graph, behavior)
    first_a = behavior.definitions[0]['id']
    assert not any(edge['from'] == first_a and edge['to'] == consume['id'] for edge in relations.edges)


@pytest.mark.parametrize('expression', ['flag and (a := b)', '(a := b) if flag else None'])
def test_conditional_assignment_keeps_old_definition_and_unresolved_identity(expression):
    setup = 'flag=False\na=[]\nb=[]\n' + expression + '\n'
    assert run_python(setup + 'import json; print(json.dumps(a is b))') is False
    behavior = index(setup + 'consume(a, b)\n')
    left, right = calls(behavior, 'consume')[0]['arguments']
    assert len(left['definition_versions']) == 2
    assert left['value_identity'] is None
    assert right['identity_kind'] == 'fresh_allocation'


def test_subscript_mutation_reads_base_and_index_without_rebinding_them():
    setup = 'a=[0]\ni=0\na[i]=7\n'
    assert run_python(setup + 'import json; print(json.dumps([a, i]))') == [[7], 0]
    behavior = index(setup + 'consume(a, i)\n')
    assert len(behavior.definitions) == 2
    left, right = calls(behavior, 'consume')[0]['arguments']
    assert left['value_identity'] == behavior.definitions[0]['value_identity']
    assert right['value_identity'] == behavior.definitions[1]['value_identity']
    mutation = behavior.graph.nodes[2]
    assert not mutation['defs']
    assert mutation['uses'] == {(0, 'a'), (0, 'i')}
    assert mutation['state_names'] == {'a'}


def test_member_assignment_rhs_rebinding_does_not_claim_textual_receiver_identity():
    code = 'from types import SimpleNamespace\na=SimpleNamespace()\nb=SimpleNamespace()\nold=a\na.x=(a := b)\n'
    assert run_python(code + 'import json; print(json.dumps([hasattr(old,"x"), b.x is b]))') == [False, True]
    behavior = index(code)
    write = next(op for op in behavior.operations if op['kind'] == 'member_write')
    assert write['receiver']['value_identity'] is None
    assert 'assignment_evaluation_order_rebinding' in write['receiver']['unknowns']
    assert len(write['receiver']['definition_versions']) == 2


def test_factory_result_tokens_do_not_assert_independent_objects():
    code = '''shared = []
def factory():
    return shared
a = factory()
b = factory()
'''
    assert run_python(code + '\nimport json; print(json.dumps(a is b))') is True
    behavior = index(code)
    results = [d for d in behavior.definitions if d['value_kind'] == 'call_result']
    assert len(results) == 2
    assert all(d['identity_kind'] == 'symbolic_value' for d in results)
    assert all('return_value_may_alias_other_values' in d['unknowns'] for d in results)


def test_callback_registration_is_a_value_relation_not_invocation():
    code = '''events = []
def callback():
    events.append('callback')
def register(cb):
    return None
register(callback)
'''
    assert run_python(code + '\nimport json; print(json.dumps(events))') == []
    behavior = index(code)
    registration = calls(behavior, 'register')[0]
    assert registration['callback_values']
    assert registration['callback_values'][0]['invocation'] == 'not_established'
    append = calls(behavior, 'append')[0]
    assert append['frames'][0]['invocation'] == 'not_established'
    assert not any(edge['before'] == registration['id'] and edge['after'] == append['id']
                   for edge in behavior.order)


def test_guards_handler_frames_and_observation_positions_are_preserved():
    code = '''def f(r, flag):
    if flag:
        r.start()
    else:
        r.stop()
    try:
        list(r.consume())
    except ValueError:
        assert r.closed
'''
    behavior = index(code)
    start, stop = calls(behavior, 'start')[0], calls(behavior, 'stop')[0]
    assert start['guards'][0]['polarity'] is True
    assert stop['guards'][0]['polarity'] is False
    check = next(op for op in behavior.operations if op['kind'] == 'assert')
    assert check['frames'][-1]['branch'] == 'except_clause'
    closed = next(op for op in behavior.operations if op['name'] == 'closed')
    assert closed['receiver']['value_identity'] == calls(behavior, 'consume')[0]['receiver']['value_identity']
    assert check['observation']['effects'] == 'not_assumed_pure'
    assert check['observation']['reached'] == 'not_established'


def test_branch_join_does_not_choose_one_of_two_allocations():
    behavior = index('def f(flag):\n if flag:\n  a=[]\n else:\n  a=[]\n a.append(1)\n')
    receiver = calls(behavior, 'append')[0]['receiver']
    assert len(receiver['definition_versions']) == 2
    assert receiver['value_identity'] is None
    assert 'multiple_or_unresolved_reaching_values' in receiver['unknowns']


def test_closure_keeps_cell_binding_without_freezing_definition_time_value():
    behavior = index('def factory():\n x=[]\n def cb():\n  print(x)\n x=[]\n return cb\n')
    argument = calls(behavior, 'print')[0]['arguments'][0]
    assert argument['binding'] == argument['lexical_cell']
    assert argument['value_identity'] is None
    assert 'lexical_cell_value_at_invocation' in argument['unknowns']


@pytest.mark.parametrize('suffix,code', [
    ('.go', 'package p\nfunc f(a []int) { b := a; consume(b) }'),
    ('.rs', 'fn f(a: Vec<i32>) { let b = a; consume(b); }'),
])
def test_go_rust_value_assignment_does_not_use_python_reference_rule(suffix, code):
    behavior = index(code, suffix)
    b = next(d for d in behavior.definitions if d['binding'][1] == 'b')
    assert b['value_identity'] is None
    assert 'value_assignment_does_not_establish_object_alias' in b['unknowns']


def test_view_reuses_index_and_parse_failures_remain_data():
    behavior = index('x = make()\nconsume(x)\n')
    selected = calls(behavior, 'consume')[0]
    view = behavior.view([selected['statement']])
    assert view['operations'][0] is selected
    assert json.loads(json.dumps(view))['operations'][0]['name'] == 'consume'
    graph = SourceGraph({'id': 'broken', 'path': 'broken.py', 'raw': b'def broken('})
    bad = BehaviorIndex(graph)
    assert bad.operations == []
    assert bad.view([])['issues'] == graph.issues


def test_loop_allocations_keep_iteration_identity_unknown_after_the_loop():
    behavior = index('for i in range(2):\n a=[]\n b=a\na.append(1)\n')
    receiver = calls(behavior, 'append')[0]['receiver']
    assert receiver['value_identity'] is None
    allocation = next(d for d in behavior.definitions if d['value_kind'] == 'fresh_allocation')
    assert 'dynamic_iteration_identity' in allocation['unknowns']


def test_member_write_waits_for_its_value_operation():
    behavior = index('obj.result = compute()\n')
    write = next(op for op in behavior.operations if op['kind'] == 'member_write')
    compute = calls(behavior, 'compute')[0]
    assert write['arguments'][0]['role'] == 'written_value'
    assert {'before': compute['id'], 'after': write['id'], 'kind': 'write_value_evaluation',
            'condition': 'both_events_reached_in_same_activation'} in behavior.order


def test_nonlocal_rebinding_does_not_freeze_the_outer_cells_value():
    code = '''def f():
    a = []
    def change():
        nonlocal a
        a = [1]
    change()
    return a
'''
    assert run_python(code + '\nimport json; print(json.dumps(f()))') == [1]
    behavior = index(code.replace('return a', 'consume(a)'))
    argument = calls(behavior, 'consume')[0]['arguments'][0]
    assert argument['value_identity'] is None
    assert 'lexical_cell_can_be_rebound_by_another_frame' in argument['unknowns']


@pytest.mark.parametrize('language,code', [
    ('node', 'function f(x) { if (x) return; else return; throw Error("unreachable"); } f(true); f(false); console.log("[]");'),
    ('go', 'package main\nimport "fmt"\nfunc f(x bool) { if x { return } else { return }; panic("unreachable") }\nfunc main() { f(true); f(false); fmt.Println("[]") }'),
    ('rustc', 'fn f(x: bool) { if x { return; } else { return; } panic!("unreachable"); }\nfn main() { f(true); f(false); println!("[]"); }'),
])
def test_cfg_exit_counterexample_runs_in_available_language_runtime(tmp_path, language, code):
    executable = shutil.which(language)
    if executable is None:
        pytest.skip(f'{language} runtime is unavailable')
    if language == 'node':
        command, environment = [executable, '-e', code], os.environ.copy()
    else:
        source = tmp_path / ('main.go' if language == 'go' else 'main.rs')
        source.write_text(code)
        environment = {**os.environ, 'GOCACHE': str(tmp_path / 'go-cache'), 'GOPATH': str(tmp_path / 'go-path'),
                       'GOTOOLCHAIN': 'local', 'GO111MODULE': 'off'}
        if language == 'go':
            command = [executable, 'run', str(source)]
        else:
            output = tmp_path / 'main'
            subprocess.run([executable, str(source), '-o', str(output)], capture_output=True, text=True, check=True, timeout=60)
            command = [str(output)]
    result = subprocess.run(command, env=environment, capture_output=True, text=True, check=True, timeout=60)
    assert json.loads(result.stdout) == []
