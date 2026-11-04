"""Behavior facts must preserve their code and uncertain execution context."""
from pathlib import Path
import os
import subprocess
import sys

from eviweave.artifacts import read_json
from eviweave.evidence import SourceGraph
from eviweave.history import read_context, read_source_bytes
from eviweave.slice_behavior import (indexes, source_behavior, read_behavior_graph, write_behavior_graph,
                                     select_exported_behavior)
from eviweave.slicing import ContextProgram, read_slice_evidence, SliceEvidenceReader
from test_eviweave_joint_pipeline import run_pipeline


def graph(code, path='test_case.py'):
    return SourceGraph({'id': 'version', 'path': path, 'raw': code.encode()})


def test_await_yield_return_and_index_write_keep_roles_and_original_ranges():
    source = '''async def worker(box):
    box['ready'] = await initialize()
    yield box['ready']
    return box
'''
    g = graph(source)
    behavior, _ = indexes(g)
    assert {'await', 'yield', 'return', 'subscript_write', 'subscript_read'} <= {o['kind'] for o in behavior.operations}
    write = next(o for o in behavior.operations if o['kind'] == 'subscript_write')
    value = next(p for p in write['arguments'] if p['role'] == 'written_value')
    assert source.encode()[slice(*value['range'])] == b'await initialize()'
    assert any(e['operation'] == write['id'] and e['kind'] == 'write' for e in behavior.effects)
    assert any(e['after'] == write['id'] and e['kind'] == 'write_value_evaluation' for e in behavior.order)


def test_call_effects_bind_to_actual_ports_and_nested_calls_stay_composable():
    source = '''def inner(box):
    box['ready'] = True
    return box
def outer(value):
    return inner(value)
def test_case():
    state = {}
    result = outer(state)
    assert result['ready']
'''
    g = graph(source)
    start = g.raw.index(b'outer(state)')
    view = ContextProgram.from_source(g).slice('version', g.criterion(start, start + 12)['node'])
    assert len(view['calls']) == 2
    behavior, _ = indexes(g)
    inner = next(c for c in view['calls'] if c['parameters'] == ['box'])
    assert inner['arguments'][0]['ports'] == ['positional:0']
    assert inner['behavior']['return_operations']
    write = next(e for e in inner['behavior']['effect_bindings']
                 if behavior.effects[e['effect']]['kind'] == 'write')
    assert write['caller_ports'] == ['positional:0']
    assert inner['behavior']['invocation'] == 'conditional_static_call'


def test_callback_and_factory_cells_do_not_become_proven_dynamic_aliases():
    source = '''def factory():
    value = []
    def append(x):
        value.append(x)
    def read():
        return value
    return append, read
def register(callback):
    return callback
first = factory()
second = factory()
register(lambda: first[0](3))
'''
    g = graph(source)
    behavior, _ = indexes(g)
    cell = next(c for c in behavior.cells if c['binding'][1] == 'value')
    assert len(cell['uses']) >= 2
    assert cell['identity'] == 'shared_lexical_binding_per_defining_activation'
    assert 'defining_activation_and_value_at_invocation' in cell['unknowns']
    start = g.raw.index(b'register(lambda')
    view = ContextProgram.from_source(g).slice('version', g.criterion(start, start + 8)['node'])
    callbacks = [c for c in view['calls'] if c['kind'] == 'callable_value']
    assert callbacks and all(c['behavior']['invocation'] == 'passed_callable_not_observed' for c in callbacks)


def test_unknown_source_syntax_retains_issue_and_complete_raw_bytes():
    raw = 'def broken(:\n  operation(\n'
    g = graph(raw)
    facts = source_behavior(g, [])
    assert facts['issues'] and not facts['operations']
    assert g.raw.decode() == raw


def test_rust_cfg_attribute_is_retained_as_annotation_not_a_field_read():
    source = '#[cfg(feature = "grammar-extras")]\nfn check() { operation(); }\n'
    g = graph(source, 'test_case.rs')
    facts = source_behavior(g, [n['id'] for n in g.nodes])
    annotation, = [o for o in facts['operations'] if o['kind'] == 'annotation']
    assert annotation['name'] == 'cfg'
    assert 'compile_time_attribute_semantics' in annotation['unknowns']
    assert source.encode()[slice(*annotation['expression_range'])] == b'cfg(feature = "grammar-extras")'
    assert not any(o['kind'] == 'member_read' for o in facts['operations'])


def test_real_batch_exports_shared_behavior_and_deleted_script_io_for_readback(tmp_path):
    code = '''import json
from pathlib import Path
from impl import operation
context = json.loads(Path('context.json').read_text())
assert operation(context['start']) == 4
print('historical-result')
'''
    command = ("printf '{\"start\":3}\\n' >context.json\n"
               "cat >gone.py <<'PY'\n" + code + "PY\n"
               "python3 -B gone.py\npython3 -B gone.py\nrm gone.py context.json\n")
    out, directory, summary = run_pipeline(tmp_path, {'impl.py': 'def operation(value): return value + 1\n'},
                                            command, 'Preserve `operation()` behavior.')
    assert summary['shared_execution_contexts'] == 2
    graphs = [read_behavior_graph(p) for p in (directory / 'graphs').glob('*.json.gz')]
    versions = [g for g in graphs if g['path'] == '/app/gone.py']
    assert len(versions) == 1 and versions[0]['behavior']['operations']
    views = [(p, read_json(p)) for p in (directory / 'views').glob('*.json')]
    executed = [(p, v) for p, v in views if v['mode'] == 'program'
                and any(f['path'] == '/app/gone.py' for f in v['files'])]
    assert len(executed) >= 2
    reader = SliceEvidenceReader(directory)
    for path, view in executed:
        assert all('behavior' not in f for f in view['files'])
        assert view['material_links']
        packet = reader.read(path.relative_to(directory))
        historical = next(f for f in packet['behavior_sources'] if f['path'] == '/app/gone.py')
        assert read_context(historical['source']) == code
        assert historical['behavior']['operations']
        assert any(m['path'] == '/app/context.json' and read_source_bytes(m['source']) == b'{"start":3}\n'
                   for m in packet['materials'])
        assert any(m['kind'] == 'stream' and b'historical-result' in read_source_bytes(m['source'])
                   for m in packet['materials'])
        assert any(m['kind']=='output' and m['origin']=='original' and m['text']=='original-output'
                   for m in packet['candidate_materials'])
        assert any(m['kind']=='output' and m['origin']=='replay' and 'historical-result' in m['text']
                   for m in packet['candidate_materials'])
        assert any(m['kind']=='file' and m['path']=='/app/context.json' and m['text']=='{"start":3}\n'
                   for m in packet['candidate_materials'])
        assert Path(packet['collection']).exists() and Path(packet['complete_history']).exists()
    assert len(reader.graphs) <= len(graphs)


def test_static_deleted_helper_keeps_full_opaque_input_and_conditional_effects(tmp_path):
    source = '''from helper import operation
def test_case():
    script = "make := func() { x := 0; return func() { x++ } }"
    assert operation(script)
'''
    command = "cat >gone.py <<'PY'\n" + source + "PY\nrm gone.py\n"
    _, directory, _ = run_pipeline(tmp_path, {'helper.py': 'def operation(value): return True\n'}, command,
                                    'Check `operation()` and closure sharing.')
    paths = [p for p in (directory / 'views').glob('*.json')
             if any(f['path'] == '/app/gone.py' for f in read_json(p).get('files', []))]
    assert paths
    for path in paths:
        packet = read_slice_evidence(directory, path.relative_to(directory))
        assert packet['execution'] is None
        historical = next(f for f in packet['behavior_sources'] if f['path'] == '/app/gone.py')
        assert read_context(historical['source']) == source
        assert any(c['behavior']['operation'] is not None for c in packet['calls'])
        assert historical['behavior']['effects']


def test_shared_graph_compression_is_lossless_including_unknowns_and_unicode(tmp_path):
    code = 'a=[]\nb=a\na=[]\nunknown(a, b, "状态条件")\n'
    g = graph(code)
    facts = source_behavior(g, [n['id'] for n in g.nodes])
    path = tmp_path / 'graph.json.gz'
    write_behavior_graph(path, facts)
    assert read_behavior_graph(path) == facts
    first = path.read_bytes()
    write_behavior_graph(path, facts)
    assert path.read_bytes() == first


def test_observed_dynamic_binary_input_and_binary_output_remain_readable(tmp_path):
    code='''from pathlib import Path
from impl import operation
def test_payload():
    payload = next(Path('.').glob('*.bin')).read_bytes()
    assert operation(payload) == 255
test_payload()
'''
    command=("printf '\\377' >resource.bin\npython3 -B test_dynamic.py\n"
             "python3 -c 'import sys; sys.stdout.buffer.write(bytes([255]))'\nrm resource.bin\n")
    _,directory,summary=run_pipeline(tmp_path,{'impl.py':'def operation(value): return value[0]\n',
                                              'test_dynamic.py':code},command,'Preserve `operation()`.')
    path=next(p for p in (directory/'views').glob('*.json')
              if read_json(p)['mode']=='program' and any(f['path']=='/app/test_dynamic.py' for f in read_json(p)['files']))
    packet=read_slice_evidence(directory,path.relative_to(directory))
    document=next(d for d in packet['candidate_materials'] if d['kind']=='file' and d['path']=='/app/resource.bin')
    assert document['text'] is None and document['source_error']
    assert read_source_bytes(document['source'])==b'\xff'
    assert any(l['material']==document['id'] and l['relation']=='observed_input'
               for l in packet['candidate_material_links'])
    assert not any(l['material']==document['id'] and l['relation']=='literal_path_version_candidate'
                   for l in packet['candidate_material_links'])
    output=next(d for d in packet['candidate_materials']
                if d['kind']=='output' and d['origin']=='replay' and d['source'].endswith('output.bin'))
    assert output['text'] is None and read_source_bytes(output['source'])==b'\xff'
    assert summary['shared_material_executions']>0


def test_export_retains_assignment_chain_between_operation_ports():
    g = graph('original = {}\nalias = original\ncopy = alias\nconsume(copy)\n')
    nodes = [n['id'] for n in g.nodes]
    facts = source_behavior(g, nodes)
    exported = select_exported_behavior(facts, nodes)
    assignments = [e for e in exported['relations']['edges'] if e['kind'] == 'reference_assignment']
    assert len(assignments) == 2
    by_id = {d['id']: d for d in exported['definitions']}
    assert {(by_id[e['from']]['binding'][1], by_id[e['to']]['binding'][1]) for e in assignments} == {
        ('original', 'alias'), ('alias', 'copy')}


def test_closure_callable_is_a_shared_cell_even_without_argument_reads():
    g = graph('def factory(callback):\n    def invoke():\n        return callback()\n    return invoke\n')
    facts = source_behavior(g, [n['id'] for n in g.nodes])
    cell = next(c for c in facts['cells'] if c['binding'][1] == 'callback')
    invoke = next(o for o in facts['operations'] if o['name'] == 'callback')
    assert any(use['operation'] == invoke['id'] for use in cell['uses'])
    assert cell['unknowns'] == ['defining_activation_and_value_at_invocation']


def test_reader_retains_all_runtime_versions_and_unparsed_material_for_llm(tmp_path):
    code = '''import helper, importlib
from pathlib import Path
assert helper.operation() == 3
Path('helper.py').write_text('def operation(): return 12345\\n')
importlib.invalidate_caches()
importlib.reload(helper)
assert helper.operation() == 12345
'''
    broken = 'def broken(:\n  operation(\n'
    _, directory, _ = run_pipeline(tmp_path, {'helper.py': 'def operation(): return 3\n',
                                             'test_versions.py': code, 'broken.py': broken},
                                    'python3 -B test_versions.py', 'Preserve `operation()`.')
    path = next(p for p in (directory / 'views').glob('*.json') if read_json(p).get('version_alternatives'))
    packet = read_slice_evidence(directory, path.relative_to(directory))
    versions = {read_context(m['source']) for m in packet['alternative_sources']}
    assert {'def operation(): return 3\n', 'def operation(): return 12345\n'} <= versions
    records = read_json(packet['complete_history'])['records']
    assert any(broken in r['text'] for r in records)
    destination = tmp_path / 'llm-evidence.json'
    subprocess.run([sys.executable, '-m', 'eviweave', 'slice-evidence', '--directory', str(directory),
                    '--view', str(path.relative_to(directory)), '--out', str(destination)],
                   check=True, capture_output=True,
                   env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
    exported = read_json(destination)
    assert {r['material'] for r in exported['alternative_sources']} == {r['material'] for r in packet['alternative_sources']}
    assert exported['events'] and exported['complete_history']
