"""Real syntax examples for the Step D selectivity experiments."""
from eviweave.anchors import changed_lines, parse_source
from eviweave.retrieval import (focused_names, surface_queries, query_matches,
                               attach_scope_support, observed_action_jobs, observed_source_rows)


def source(path, code, identity, kind='final_workspace'):
    raw = code.encode()
    return {'id': identity, 'path': path, 'raw': raw, 'kind': kind,
            'parsed': parse_source(path, raw)}


def rules(**kwargs):
    return {'calls': [], 'types': [], 'fields': [], 'input_tokens': [], **kwargs}


def test_changed_local_variables_do_not_become_focused_queries():
    item = source('api.py', 'def send(local):\n    return local.closed\n', 'F:api')
    patch = '--- a/api.py\n+++ b/api.py\n@@ -2 +2 @@\n-    return False\n+    return local.closed\n'
    assert focused_names('', changed_lines(patch), [('api.py', item['raw'], item['parsed'])], [item]) == ['closed', 'send']


def test_changed_decorator_identifies_the_decorated_method():
    item = source('api.py', 'class Client:\n    @property\n    def closed(self):\n        return False\n', 'api')
    patch = ('--- a/api.py\n+++ b/api.py\n@@ -1,3 +1,4 @@\n class Client:\n'
             '+    @property\n     def closed(self):\n         return False\n')
    assert 'closed' in focused_names('', changed_lines(patch), [('api.py', item['raw'], item['parsed'])], [item])


def test_modified_helper_expands_to_public_caller_and_callback_reference():
    api = source('api.py', 'def helper(x):\n    return x + 1\n\ndef parse(x):\n    return helper(x)\n', 'api')
    check = source('test_api.py', 'from api import parse\nassert list(map(parse, [1])) == [2]\n', 'check')
    patch = '--- a/api.py\n+++ b/api.py\n@@ -2 +2 @@\n-    return x\n+    return x + 1\n'
    query = surface_queries('', patch, [('api.py', api['raw'], api['parsed'])], [api, check])
    assert 'parse' in query['calls']
    assert query_matches([api, check], [query], validation_only=True)


def test_receiver_family_adds_related_entry_operation():
    api = source('vm.go', 'package vm\ntype VM struct{}\nfunc (v *VM) Run() {}\nfunc (v *VM) GoCall() {}\n', 'api')
    check = source('vm_test.go', 'package vm\nfunc TestRun() { v.Run(); v.GoCall() }\n', 'check')
    patch = '--- a/vm.go\n+++ b/vm.go\n@@ -3 +3 @@\n-func (v *VM) Run() { old() }\n+func (v *VM) Run() {}\n'
    query = surface_queries('', patch, [('vm.go', api['raw'], api['parsed'])], [api, check])
    assert {'Run', 'GoCall'} <= set(query['calls'])


def test_field_match_does_not_match_same_local_variable_or_type_annotation():
    item = source('test_api.py', 'closed = False\ndef check():\n    closed = True\n    assert obj.closed\n', 'check')
    selected = query_matches([item], [rules(fields=['closed'])])
    assert len(selected) == 1
    assert [item['raw'][a:b] for a, b in selected[0]['anchors']] == [b'obj.closed']


def test_test_labels_and_docstrings_do_not_count_as_input_literals():
    item = source('api.test.ts', 'test("parse", () => { run("other") });\ntest("x", () => { run("parse") });', 'check')
    selected = query_matches([item], [rules(input_tokens=['parse'])])
    assert len(selected) == 1
    assert item['raw'][selected[0]['start']:selected[0]['end']].startswith(b'test("x"')


def test_support_closure_keeps_import_alias_class_setup_and_helper_by_source():
    code = ('import datetime as dt_mod\nENABLED = {"B601"}\n'
            'def helper(x):\n    return dt_mod.datetime.now()\n'
            'def test_send():\n    result = client.send(ENABLED)\n    assert helper(result)\n')
    item = source('test_api.py', code, 'one')
    other = source('test_api.py', code.replace('"B601"', '"B602"'), 'other')
    selected = query_matches([item], [rules(calls=['send'])])
    closure = attach_scope_support([item, other], selected)
    texts = [item['raw'][a:b].decode() for identity, a, b in closure]
    assert all(identity == 'one' for identity, a, b in closure)
    assert any(text.startswith('import datetime') for text in texts)
    assert any(text.startswith('ENABLED') for text in texts)
    assert any(text.startswith('def helper') for text in texts)


def test_arrow_function_is_a_named_callable_for_reverse_retrieval():
    item = source('api.ts', 'export const parse = (x: number) => helper(x);', 'api')
    unit, = item['parsed']['units']
    assert unit['name'] == 'parse' and 'parse' in unit['defines']


def test_non_AST_carriers_keep_appends_CLI_inputs_and_data_reads():
    commands = [
        "cat >> unit_test.go <<'GO'\nfunc TestSend() { v.Send() }\nGO\n",
        "printf '<ul><li>a</ul>' | /tmp/dasel -i html -o json",
        "cat tests/snapshots/output.snap",
        'git status --short',
        'go run /tmp/probe.go',
        "sed -n '240,360p' jobs/transform.rs",
    ]
    actions = [{'id': str(i), 'command': cmd, 'expected': {'output': ''}} for i, cmd in enumerate(commands)]
    jobs = observed_action_jobs(actions, [rules(calls=['Send'])], ['api.go'])
    assert {j['action_id'] for j in jobs} == {'0', '1', '2', '4', '5'}
    assert 'authored_validation_fragment' in jobs[0]['roles']
    assert 'subject_execution' in jobs[1]['roles']
    assert 'source_or_data_read' in jobs[2]['roles']
    assert 'source_or_data_read' in jobs[4]['roles']


def test_unmentioned_repository_tests_are_dependencies_rather_than_history_seeds():
    first = source('test_first.py', 'def test_first():\n    client.send()\n', 'first')
    second = source('test_second.py', 'def test_second():\n    client.send()\n', 'second')
    authored = source('/tmp/probe.py', 'client.send()\n', 'probe', 'historical_write')
    sources = [first, second, authored]
    rows = query_matches(sources, [rules(calls=['send'])])
    actions = [{'command': 'pytest test_first.py', 'expected': {'output': 'passed'}}]
    selected = observed_source_rows(sources, rows, actions)
    assert {r['source'] for r in selected} == {'first', 'probe'}


def test_unprinted_suite_tests_still_supply_history_entries():
    item = source('tests/test_silent.py', 'def test_state():\n    client.send()\n', 'silent')
    rows = query_matches([item], [rules(calls=['send'])])
    actions = [{'command': 'pytest -q', 'expected': {'output': '1 passed'}}]
    assert observed_source_rows([item], rows, actions) == rows


def test_go_recursive_suite_covers_unprinted_package_tests():
    item = source('sub/entry_test.go', 'package p\nfunc TestState() { client.Send() }', 'silent')
    rows = query_matches([item], [rules(calls=['Send'])])
    actions = [{'command': 'go test ./...', 'expected': {'output': 'ok p/sub'}}]
    assert observed_source_rows([item], rows, actions) == rows


def test_runner_name_filter_is_not_a_directory_selector():
    first = source('tests/test_first.py', 'def test_first():\n    client.send()\n', 'first')
    second = source('examples/test_second.py', 'def test_second():\n    client.send()\n', 'second')
    rows = query_matches([first, second], [rules(calls=['send'])])
    actions = [{'command': 'pytest -k tests', 'expected': {'output': ''}}]
    assert observed_source_rows([first, second], rows, actions) == rows


def test_interpreted_program_can_be_reached_through_a_test_helper():
    api = source('vm.go', 'package p\ntype VM struct{}\nfunc (v *VM) GoCall() {}\nfunc (v *VM) Run() {}', 'api')
    check = source('vm_test.go', 'package p\nfunc expectRun(code string) { v.Run() }\n'
                   'func TestClosure() { expectRun(`f := func() { return 1 }`) }', 'check')
    patch = '--- a/vm.go\n+++ b/vm.go\n@@ -3 +3 @@\n-func (v *VM) GoCall() { old() }\n+func (v *VM) GoCall() {}\n'
    query = surface_queries('', patch, [('vm.go', api['raw'], api['parsed'])], [api, check], wrappers=True)
    assert 'expectRun' in query['calls']
    selected = query_matches([api, check], [query], validation_only=True, embedded=True)
    assert any(b'func TestClosure' in check['raw'][r['start']:r['end']] for r in selected)


def test_code_inside_an_edit_string_is_an_embedded_operation_carrier():
    item = source('edit.py', 's = s.replace("old", "client.send(1)")\n', 'edit', 'inline_script')
    assert not query_matches([item], [rules(calls=['send'])])
    selected = query_matches([item], [rules(calls=['send'])], embedded=True)
    assert len(selected) == 1
    assert [item['raw'][a:b] for a, b in selected[0]['anchors']] == [b'"client.send(1)"']


def test_plain_issue_directive_can_retrieve_a_literal_input():
    item = source('test_api.py', 'check("# nosec-begin B602")\n', 'check')
    query = surface_queries('Support # nosec-begin regions.', '', [], [item], wrappers=True)
    assert '# nosec-begin' in query['input_tokens']
    assert query_matches([item], [query], embedded=True)
