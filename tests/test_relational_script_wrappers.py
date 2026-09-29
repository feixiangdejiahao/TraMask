"""Independent executable scripts verify wrapper scope and source provenance."""
import ast
import os
import subprocess
import sys

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.script_wrappers import prepare_script_sources, wrap_python_script
from relational_gap.transforms import enumerate_transforms


def script(code, path='history/check.py', language='python'):
    return Source(path, code, language, origin='trajectory', step=4, written_path='/tmp/check.py')


def execute_wrapped(prepared):
    assert prepared['status'] == 'wrapped', prepared['record']
    namespace = {'__name__': 'wrapped_validation'}
    exec(compile(prepared['source'].code, prepared['source'].path, 'exec'), namespace)
    namespace[prepared['record']['wrapper_name']]()
    return namespace


def test_helpers_preserve_module_global_bindings_and_repeated_execution():
    source = script('''value = 1
def read():
    return value
assert read() == 1
value = 2
assert read() == 2
''')
    prepared = wrap_python_script(source)
    namespace = execute_wrapped(prepared)
    assert namespace['value'] == 2
    assert namespace['read'].__closure__ is None
    namespace[prepared['record']['wrapper_name']]()
    assert namespace['value'] == 2
    assert prepared['record']['global_bindings'] == ['value']
    tree = ast.parse(prepared['source'].code)
    assert isinstance(tree.body[0], ast.FunctionDef) and tree.body[0].name == 'read'


def test_main_body_is_preserved_and_else_is_not_executed():
    source = script('''def double(value):
    return value * 2
if __name__ == "__main__":
    result = double(6)
    assert result == 12
else:
    raise RuntimeError("script is meant for direct execution")
''')
    prepared = wrap_python_script(source)
    namespace = execute_wrapped(prepared)
    assert namespace['result'] == 12
    assert len(prepared['record']['main_guard_spans']) == 1
    assert prepared['record']['assertion_count'] == 1


def test_multiline_string_bytes_and_unicode_spans_are_unchanged():
    source = script('''label = "界🙂"
payload = """first
unindented
  indented
last"""
assert payload == "first\\nunindented\\n  indented\\nlast"
assert label == "界🙂"
''')
    prepared = wrap_python_script(source)
    namespace = execute_wrapped(prepared)
    assert namespace['payload'] == 'first\nunindented\n  indented\nlast'
    for mapping in prepared['record']['mappings']:
        original = mapping['source_span']
        generated = mapping['generated_span']
        assert source.data[original['start_byte']:original['end_byte']] == prepared['source'].data[generated['start_byte']:generated['end_byte']]


def test_multiline_string_inside_main_guard_keeps_exact_value():
    source = script('''if __name__ == "__main__":
    payload = """a
b
    c"""
    assert payload == "a\\nb\\n    c"
''')
    namespace = execute_wrapped(wrap_python_script(source))
    assert namespace['payload'] == 'a\nb\n    c'


def test_loop_and_exception_bindings_stay_global_but_comprehension_targets_do_not():
    source = script('''values = [index for index in range(3)]
for item in values:
    last = item
try:
    raise ValueError("x")
except ValueError as problem:
    message = str(problem)
assert last == 2
assert message == "x"
''')
    prepared = wrap_python_script(source)
    namespace = execute_wrapped(prepared)
    assert {'values', 'item', 'last', 'problem', 'message'} <= set(prepared['record']['global_bindings'])
    assert 'index' not in prepared['record']['global_bindings']
    assert 'index' not in namespace and 'problem' not in namespace


def test_eager_default_capture_of_moved_binding_is_unsupported():
    result = wrap_python_script(script('''limit = 3
def value(default=limit):
    return default
assert value() == 3
'''))
    assert result['status'] == 'unsupported'
    assert result['record']['reason'] == 'eager_definition_depends_on_moved_script_binding'


def test_import_after_executable_setup_preserves_order_and_global_binding(monkeypatch):
    import builtins
    import types
    source = script('''setup()
import imaginary
assert imaginary.check()
''')
    result = wrap_python_script(source)
    assert result['status'] == 'wrapped'
    events = []
    module = types.ModuleType('imaginary')
    module.check = lambda: True
    original_import = builtins.__import__
    def import_hook(name, *args, **kwargs):
        if name == 'imaginary':
            events.append('import')
            return module
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', import_hook)
    namespace = {'setup': lambda: events.append('setup')}
    exec(result['source'].code, namespace)
    assert events == []
    namespace[result['record']['wrapper_name']]()
    assert events == ['setup', 'import']
    assert namespace['imaginary'] is module


def test_late_import_remains_visible_to_retained_generator_helper():
    result = wrap_python_script(script('''events = []
events.append('setup')
from math import sqrt as root
def gen():
    yield root(9)
values = list(gen())
assert values == [3]
'''))
    namespace = execute_wrapped(result)
    assert namespace['events'] == ['setup']
    assert list(namespace['gen']()) == [3]
    assert 'root' in result['record']['global_bindings']
    frontend = extract_frontend([result['source']])
    corpus = to_emitter_corpus(frontend)
    assert all(test['name'] != '<script>' for test in corpus['tests'].values())
    test_id, = corpus['tests']
    emitted = emit(corpus, [{'id': 'same_source', 'base_test_id': test_id, 'edits': []}])
    assert not emitted['unsupported']
    assert 'def gen():' in emitted['files'][result['source'].path]
    assert not any('gen' == item.get('test_name') for item in emitted['obligations'])


def test_late_import_is_not_lifted_across_eager_definition_dependency():
    result = wrap_python_script(script('''ready = True
from math import pi
def value(default=pi):
    return default
assert value() > 3
'''))
    assert result['status'] == 'unsupported'
    assert result['record']['reason'] == 'eager_definition_depends_on_moved_script_binding'


def test_dynamic_locals_and_annotations_do_not_silently_change_scope():
    dynamic = wrap_python_script(script('value = 1\nassert locals()["value"] == 1\n'))
    annotated = wrap_python_script(script('value: int = 1\nassert value == 1\n'))
    assert dynamic['record']['reason'] == 'dynamic_namespace_requires_script_scope'
    assert annotated['record']['reason'] == 'annotated_module_binding_requires_annotation_lowering'


def test_prints_remain_explicitly_unchecked_and_preparation_does_not_execute(capsys):
    result = wrap_python_script(script('print("not an assertion")\n'))
    assert result['status'] == 'wrapped'
    assert result['record']['observation_status'] == 'unchecked_output_or_no_assertion'
    assert capsys.readouterr().out == ''
    execute_wrapped(result)
    assert capsys.readouterr().out == 'not an assertion\n'


def test_preparation_only_wraps_historical_scripts_and_retains_registered_tests():
    ordinary = Source('module.py', 'assert value\n', 'python')
    existing = script('def test_original():\n    assert True\n')
    go = script('package main\nfunc main() {}\n', 'history/check.go', 'go')
    result = prepare_script_sources([ordinary, existing, go])
    assert result['sources'] == [ordinary, existing, go]
    assert result['records'][0]['reason'] == 'no_executable_script_statements'
    assert result['records'][1]['reason'] == 'script_wrapper_language_not_supported'


def test_wrapped_script_flows_through_frontend_transforms_and_existing_emitter():
    first = script('''def accept(value):
    return isinstance(value, str)
payload = "red"
assert accept(payload)
''', 'history/first.py')
    second = script('''def accept(value):
    return isinstance(value, str)
payload = "blue"
assert accept(payload)
''', 'history/second.py')
    prepared = prepare_script_sources([first, second])
    assert all(row['status'] == 'wrapped' for row in prepared['records'])
    frontend = extract_frontend(prepared['sources'])
    corpus = to_emitter_corpus(frontend)
    assert len(corpus['tests']) == 2
    assert all(test['owner_kind'] == 'registered_test' for test in corpus['tests'].values())
    # Same imported callee identity gives cross-file alignment without guessing
    # that unrelated source-local accept definitions are interchangeable.
    for donor in corpus['donors']:
        for port in donor.get('input_slots', []):
            if port['callee'] == 'accept':
                port['callee_identity'] = {'canonical': 'independent_fixture::accept', 'resolution': 'import_symbol'}
    candidates = enumerate_transforms(corpus)['candidates']
    assert candidates
    output = emit(corpus, candidates)
    assert not output['unsupported']
    for path, code in output['files'].items():
        namespace = {'__name__': 'wrapped_validation'}
        exec(compile(code, path, 'exec'), namespace)
        for row in output['obligations'] + output['controls']:
            if row['path'] == path:
                namespace[row['test_name']]()


def test_wrapper_output_and_provenance_are_deterministic():
    source = script('import math\nassert math.sqrt(9) == 3\n')
    first, second = wrap_python_script(source), wrap_python_script(source)
    assert first['source'].code == second['source'].code
    assert first['record'] == second['record']


def test_existing_async_test_definition_does_not_leave_module_validation_at_collection():
    source = script('''import asyncio
events = []
async def test_validation():
    events.append('validated')
    await asyncio.sleep(0)
    assert events == ['validated']
asyncio.run(test_validation())
assert events == ['validated']
''')
    prepared = prepare_script_sources([source])
    record, = prepared['records']
    wrapped, = prepared['sources']
    assert record['status'] == 'wrapped'
    namespace = {'__name__': 'collection_only'}
    exec(wrapped.code, namespace)
    assert 'events' not in namespace
    assert 'test_validation' in namespace
    namespace[record['wrapper_name']]()
    assert namespace['events'] == ['validated']
    assert record['global_bindings'] == ['events']
    assert any('asyncio.run(test_validation())' in wrapped.data[m['generated_span']['start_byte']:m['generated_span']['end_byte']].decode()
               for m in record['mappings'] if m['kind'] == 'copied_script_line')


def test_failing_module_action_still_fails_wrapped_control_with_existing_test():
    source = script('''def test_named():
    assert True
def validate():
    raise RuntimeError('source validation failed')
validate()
''')
    prepared = prepare_script_sources([source])
    namespace = {}
    exec(prepared['sources'][0].code, namespace)
    with pytest.raises(RuntimeError, match='source validation failed'):
        namespace[prepared['records'][0]['wrapper_name']]()


def test_called_generator_helper_preserves_public_binding_and_source_calls():
    source = script('''def test_stream():
    yield 'first'
    yield 'second'
values = list(test_stream())
assert values == ['first', 'second']
assert test_stream.__name__ == 'test_stream'
assert test_stream.__qualname__ == 'test_stream'
''')
    prepared = wrap_python_script(source)
    namespace = execute_wrapped(prepared)
    protection, = prepared['record']['generator_helper_protections']
    assert namespace['test_stream'] is namespace[protection['internal_name']]
    assert namespace['test_stream'].__test__ is False
    assert 'values = list(test_stream())' in prepared['source'].code
    frontend = extract_frontend([prepared['source']])
    assert [t['name'] for t in frontend['tests']] == [prepared['record']['wrapper_name']]
    for mapping in prepared['record']['mappings']:
        if mapping['kind'] in {'renamed_generator_definition', 'generated_helper_collection_protection'}:
            continue
        before, after = mapping['source_span'], mapping['generated_span']
        assert source.data[before['start_byte']:before['end_byte']] == prepared['source'].data[after['start_byte']:after['end_byte']]


def test_generator_helper_is_not_collected_even_without_module_actions(tmp_path):
    source = script('''def test_stream():
    yield 1
    yield 2
def test_consumer():
    assert list(test_stream()) == [1, 2]
''', 'test_helpers.py')
    prepared = prepare_script_sources([source])
    record, = prepared['records']
    assert record['status'] == 'helpers_protected'
    assert record['wrapper_name'] is None
    target = tmp_path / 'test_helpers.py'
    target.write_text(prepared['sources'][0].code)
    run = subprocess.run([sys.executable, '-m', 'pytest', '-q', str(target)], capture_output=True, text=True,
                         cwd=tmp_path, timeout=15, env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'))
    assert run.returncode == 0, run.stdout + run.stderr
    assert '1 passed' in run.stdout
    assert [t['name'] for t in extract_frontend(prepared['sources'])['tests']] == ['test_consumer']


def test_async_generator_helper_and_async_module_runner_keep_actions():
    source = script('''import asyncio
async def test_stream():
    yield 2
    yield 5
async def collect():
    return [value async for value in test_stream()]
values = asyncio.run(collect())
assert values == [2, 5]
''')
    prepared = wrap_python_script(source)
    namespace = execute_wrapped(prepared)
    assert namespace['values'] == [2, 5]
    assert namespace['test_stream'].__name__ == 'test_stream'
    assert len(prepared['record']['generator_helper_protections']) == 1


def test_decorated_fixture_generator_is_not_renamed_or_reclassified():
    source = script('''import pytest
@pytest.fixture
def test_stream():
    yield 1
def test_consumer(test_stream):
    assert test_stream == 1
''')
    prepared = prepare_script_sources([source])
    assert prepared['sources'][0] is source
    assert prepared['records'][0]['status'] == 'unchanged'


def test_shadowed_calls_and_nested_generator_bodies_do_not_prove_helper_role():
    source = script('''def test_stream():
    yield 1
def consume(test_stream):
    return list(test_stream())
def test_regular():
    def inner():
        yield 1
    assert list(inner()) == [1]
''')
    prepared = prepare_script_sources([source])
    assert prepared['sources'][0] is source
    assert prepared['records'][0]['status'] == 'unchanged'


@pytest.mark.parametrize('body', [
    'return [test_stream() for test_stream in providers]',
    'test_stream = providers[0]\n    def inner():\n        global test_stream\n    return test_stream()',
])
def test_comprehension_and_nested_global_declarations_preserve_binding_uncertainty(body):
    source = script('def test_stream():\n    yield 1\ndef consume(providers):\n    ' + body + '\n')
    prepared = prepare_script_sources([source])
    assert prepared['sources'][0] is source


def test_existing_test_default_still_preserves_eager_scope_boundary():
    source = script('''limit = 3
def test_value(default=limit):
    assert default == 3
test_value()
''')
    prepared = prepare_script_sources([source])
    assert prepared['sources'][0] is source
    assert prepared['records'][0]['reason'] == 'eager_definition_depends_on_moved_script_binding'


def test_repository_sources_with_generator_helpers_are_not_rewritten():
    original = Source('test_original.py', 'def test_stream():\n    yield 1\nassert list(test_stream()) == [1]\n', 'python')
    prepared = prepare_script_sources([original])
    assert prepared['sources'] == [original]
    assert prepared['records'] == []


def execute_typescript_as_javascript(prepared):
    import shutil
    import subprocess
    import pytest

    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed for independent callback execution')
    assert prepared['status'] == 'wrapped', prepared['record']
    name = prepared['record']['wrapper_import']['name']
    registration = "import { test as " + name + " } from 'vitest';"
    replacement = 'const __pending = []; const ' + name + ' = (name, body) => __pending.push(Promise.resolve().then(body));'
    code = prepared['source'].code.replace(registration, replacement)
    execution = subprocess.run([node, '--input-type=module', '-e', code + '\nawait Promise.all(__pending);'],
                               text=True, capture_output=True, timeout=20)
    assert execution.returncode == 0, execution.stderr
    return execution.stdout


def test_typescript_wrapper_keeps_helper_closures_and_statement_order():
    from relational_gap.script_wrappers import wrap_typescript_script
    source = script('''import assert from 'node:assert/strict';
let current = 1;
function read() { return current; }
assert.equal(read(), 1);
current = 7;
assert.equal(read(), 7);
console.log('checked');
''', 'history/check.ts', 'typescript')
    prepared = wrap_typescript_script(source)
    assert execute_typescript_as_javascript(prepared) == 'checked\n'
    assert prepared['record']['binding_strategy'].startswith('imports_module_scoped')
    frontend = extract_frontend([prepared['source']])
    assert len(frontend['tests']) == 1
    assert frontend['tests'][0]['owner_kind'] == 'registered_test'


def test_typescript_multiline_templates_keep_exact_bytes_and_utf8_mappings():
    from relational_gap.script_wrappers import wrap_typescript_script
    source = script('''import assert from 'node:assert/strict';
const value = `界🙂
no prefix
  original prefix`;
assert.equal(value, '界🙂\\nno prefix\\n  original prefix');
''', 'history/check.ts', 'typescript')
    prepared = wrap_typescript_script(source)
    execute_typescript_as_javascript(prepared)
    for mapping in prepared['record']['mappings']:
        original, generated = mapping['source_span'], mapping['generated_span']
        assert source.data[original['start_byte']:original['end_byte']] == prepared['source'].data[generated['start_byte']:generated['end_byte']]


def test_typescript_top_level_await_uses_async_callback_and_prints_remain_unchecked():
    from relational_gap.script_wrappers import wrap_typescript_script
    source = script("const value = await Promise.resolve(3);\nconsole.log(value);\n", 'history/async.ts', 'typescript')
    prepared = wrap_typescript_script(source)
    assert prepared['record']['asynchronous'] is True
    assert prepared['record']['observation_status'] == 'unchecked_output_or_no_assertion'
    assert execute_typescript_as_javascript(prepared) == '3\n'


def test_typescript_exports_are_explicitly_unsupported_and_existing_tests_are_retained():
    from relational_gap.script_wrappers import wrap_typescript_script
    exported = script('export const value = 1;\nconsole.log(value);\n', 'history/exports.ts', 'typescript')
    result = wrap_typescript_script(exported)
    assert result['status'] == 'unsupported'
    assert result['record']['reason'] == 'exported_module_binding_requires_original_module_scope'
    existing = script("import { test } from 'vitest';\ntest('old', () => { console.log(3); });\n", 'history/old.ts', 'typescript')
    prepared = prepare_script_sources([existing])
    assert prepared['sources'][0] is existing
    assert prepared['records'][0]['reason'] == 'registered_test_definitions_present'


def test_typescript_source_binding_named_test_stays_in_callback_scope():
    from relational_gap.script_wrappers import wrap_typescript_script
    source = script("const test = 'original';\nconsole.log(test);\n", 'history/names.ts', 'typescript')
    assert execute_typescript_as_javascript(wrap_typescript_script(source)) == 'original\n'


def test_typescript_wrapper_emits_changed_clone_and_source_control():
    from relational_gap.script_wrappers import wrap_typescript_script
    prepared = wrap_typescript_script(script("console.log('visible');\n", 'history/check.ts', 'typescript'))
    frontend = extract_frontend([prepared['source']])
    corpus = to_emitter_corpus(frontend)
    test = next(iter(corpus['tests'].values()))
    value = next(item for item in frontend['values'] if item['text'] == "'visible'")
    output = emit(corpus, [{'id': 'new_script_input', 'base_test_id': test['id'], 'source_test_ids': [],
                           'edits': [{'span': value['span'], 'before': "'visible'", 'after': "'changed'"}]}])
    assert not output['unsupported']
    assert len(output['obligations']) == len(output['controls']) == 1
    copied = dict(prepared)
    copied['source'] = Source(prepared['source'].path, next(iter(output['files'].values())), 'typescript')
    assert sorted(execute_typescript_as_javascript(copied).splitlines()) == ['changed', 'visible', 'visible']
