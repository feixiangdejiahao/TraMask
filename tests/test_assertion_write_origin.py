"""Static binding/path claims only; no subject execution or oracle verdicts."""
import ast
import json
from pathlib import Path

import pytest

from prototypes.assertion_write_origin import analyze_assertion


LIBRARY = '''class Channel:
    def __init__(obj):
        obj.done = False
    def consume(obj):
        yield from obj.chunks()
        obj.finish()
    def chunks(obj):
        yield b"chunk"
    def finish(obj):
        obj.done = True
'''


def analyze(library=LIBRARY, body=None, imports='from lib import Channel', extra=None):
    body = body or '    stream = Channel()\n    list(stream.consume())\n    assert stream.done is True\n'
    test = imports+'\ndef test_case():\n'+body
    sources = {'lib.py': library, 'test_case.py': test, **(extra or {})}
    line = next(n.lineno for n in ast.walk(ast.parse(test)) if isinstance(n, ast.Assert))
    return analyze_assertion(sources, 'test_case.py', line), sources


def bound(result):
    return next(row for row in result['reads'] if row['status']=='statically_bound_partial_slice')


def test_bound_field_writers_and_generator_normal_call_path():
    result, sources = analyze()
    row = bound(result)
    assert row['binding']['class_id'] == 'lib.Channel'
    assert [(w['method'], w['value']) for w in row['writers']] == [('__init__', 'False'), ('finish', 'True')]
    path = next(p for p in row['writer_paths'] if p['root']['method']=='consume' and p['writer_method']=='finish')
    assert [(e['caller'], e['callee']) for e in path['calls']] == [('consume', 'finish')]
    assert path['requires_generator_runtime_binding'] is True
    assert 'generator_creation_resume_and_exhaustion_not_resolved' in row['unknown']
    assert any(e['kind']=='generator_suspension_or_abandonment' for e in path['calls'][0]['possible_bypass_sites'])
    for writer in row['writers']:
        span = writer['span']
        original = sources[span['path']].encode()[span['start_byte']:span['end_byte']].decode()
        assert original.endswith(writer['value'])


def test_source_renaming_keeps_structure_without_keyword_rules():
    original, _ = analyze()
    renamed = LIBRARY.replace('Channel', 'Ledger').replace('done', 'settled').replace('consume', 'advance').replace('finish', 'commit').replace('obj', 'record')
    changed, _ = analyze(renamed, '    handle = Ledger()\n    list(handle.advance())\n    assert handle.settled is True\n', 'from lib import Ledger')
    a, b = bound(original), bound(changed)
    assert len(a['writers']) == len(b['writers']) == 2
    assert len(a['writer_paths']) == len(b['writer_paths'])
    assert b['storage_field'] == 'settled'
    assert {w['method'] for w in b['writers']} == {'__init__', 'commit'}


def test_same_named_field_in_unrelated_class_cannot_supply_writer():
    library = LIBRARY + '\nclass Other:\n    def __init__(self):\n        self.done = 123\n'
    result, _ = analyze(library, '    a = Channel()\n    b = Other()\n    list(a.consume())\n    assert b.done == 123\n', 'from lib import Channel, Other')
    row = bound(result)
    assert row['binding']['class_id'] == 'lib.Other'
    assert [w['value'] for w in row['writers']] == ['123']
    assert [p['root']['method'] for p in row['writer_paths']] == ['__init__']


def test_same_class_different_object_does_not_contribute_operation():
    result, _ = analyze(body='    first = Channel()\n    second = Channel()\n    list(first.consume())\n    assert second.done is False\n')
    assert all(p['root']['method']=='__init__' for p in bound(result)['writer_paths'])


def test_local_alias_preserves_allocation_and_operation_binding():
    result, _ = analyze(body='    first = Channel()\n    alias = first\n    list(alias.consume())\n    assert first.done is True\n')
    assert any(p['root']['method']=='consume' for p in bound(result)['writer_paths'])


@pytest.mark.parametrize('assignment, reason', [
    ('    if enabled:\n        stream = Channel()\n', 'conditional_local_binding'),
    ('    stream = factory()\n', 'unresolved_constructor'),
    ('    stream = Channel()\n    stream, ignored = pair\n', 'destructured_receiver_binding'),
    ('    stream = Channel()\n    with manager() as stream:\n        pass\n', 'unsupported_receiver_binding_write'),
    ('    stream = Channel()\n    stream += another\n', 'mutated_receiver_binding'),
])
def test_unknown_receiver_writes_do_not_reuse_old_binding(assignment, reason):
    result, _ = analyze(body=assignment+'    assert stream.done\n')
    assert result['reads'][0]['status']=='unsupported'
    assert result['reads'][0]['reason']==reason


def test_constructor_import_alias_and_package_star_reexport():
    package = {'pkg/__init__.py': 'from .objects import *\n', 'pkg/objects.py': '__all__ = ["Channel"]\n'+LIBRARY}
    result, _ = analyze(imports='from pkg import Channel as Resource', body='    stream = Resource()\n    assert stream.done is False\n', extra=package)
    assert bound(result)['binding']['class_id']=='pkg.objects.Channel'


def test_nonexported_star_class_is_not_invented():
    package = {'pkg/__init__.py': 'from .objects import *\n', 'pkg/objects.py': '__all__ = []\n'+LIBRARY}
    result, _ = analyze(imports='from pkg import Channel', extra=package)
    assert result['reads'][0]['reason']=='unresolved_constructor'


@pytest.mark.parametrize('prefix', ['    Channel = factory\n', '    if enabled:\n        Channel = factory\n'])
def test_constructor_shadowing_is_not_bound_to_import(prefix):
    result, _ = analyze(body=prefix+'    stream = Channel()\n    assert stream.done\n')
    assert result['reads'][0]['reason']=='constructor_symbol_shadowed_by_assignment'


def test_constructor_parameter_shadowing_is_explicitly_unsupported():
    sources={'lib.py':LIBRARY, 'test_case.py':'from lib import Channel\ndef test_case(Channel):\n    stream = Channel()\n    assert stream.done\n'}
    result=analyze_assertion(sources,'test_case.py',4)
    assert result['reads'][0]['reason']=='constructor_symbol_shadowed_by_parameter'


def test_local_factory_definition_does_not_reuse_imported_class_type():
    result, _ = analyze(body='    def Channel():\n        return factory()\n    stream = Channel()\n    assert stream.done\n')
    assert result['reads'][0]['reason']=='constructor_symbol_shadowed_by_definition'


def test_rebound_exported_class_is_not_resolved_as_original_class():
    result, _ = analyze(LIBRARY+'\nChannel = factory\n')
    assert result['reads'][0]['reason']=='unresolved_constructor'


def test_custom_new_may_return_different_class_and_is_unsupported():
    result, _ = analyze(LIBRARY+'\n    def __new__(cls):\n        return other\n')
    assert result['reads'][0]['reason']=='custom_constructor_type_unresolved'


def test_direct_property_alias_follows_storage_field():
    library=LIBRARY.replace('obj.done', 'obj._done')+'\n    @property\n    def done(this):\n        return this._done\n'
    result, _ = analyze(library)
    row=bound(result)
    assert row['observed_field']=='done' and row['storage_field']=='_done'
    assert row['property_aliases'][0]['storage_attribute']=='_done'


def test_effectful_property_is_not_silently_read_or_inlined():
    library=LIBRARY.replace('obj.done', 'obj._done')+'\n    @property\n    def done(this):\n        return this.refresh()\n'
    result, _ = analyze(library)
    assert result['reads'][0]['reason']=='property_not_direct_field_alias'


def test_finally_call_is_not_labelled_bypassed_by_its_protected_yield():
    library=LIBRARY.replace('        yield from obj.chunks()\n        obj.finish()', '        try:\n            yield from obj.chunks()\n        finally:\n            obj.finish()')
    result, _ = analyze(library)
    path=next(p for p in bound(result)['writer_paths'] if p['root']['method']=='consume' and p['writer_method']=='finish')
    assert path['calls'][0]['possible_bypass_sites']==[]
    assert any(c['kind']=='Try' and c['branch']=='finalbody' for c in path['calls'][0]['contexts'])


def test_rebound_method_receiver_cannot_write_original_class_field():
    library=LIBRARY.replace('        obj.done = True', '        obj = another\n        obj.done = True')
    result, _ = analyze(library)
    assert [w['method'] for w in bound(result)['writers']]==['__init__']


def test_non_ascii_byte_spans_and_subject_top_level_never_execute():
    library='raise RuntimeError("do not execute")\n# 中文\n'+LIBRARY
    result, sources=analyze(library)
    for writer in bound(result)['writers']:
        s=writer['span'];text=sources[s['path']].encode()[s['start_byte']:s['end_byte']].decode()
        assert text.startswith('obj.done =')


@pytest.mark.parametrize('case, test_path, line, initialization, closing, entry', [
    ('N01','tests/models/test_responses.py',941,733,1194,'iter_json'),
    ('N02','tests/test_multipart_response.py',117,554,1005,'iter_multipart'),
])
def test_frozen_real_corpus_extracts_initialization_close_and_operation_path(case,test_path,line,initialization,closing,entry):
    corpus=Path(__file__).resolve().parents[1]/f'results/relational_gap_20260928/batch7/{case}/corpus.json'
    if not corpus.exists():
        pytest.skip('Optional frozen development corpus is absent')
    result=analyze_assertion(json.loads(corpus.read_text())['sources'],test_path,line)
    row=bound(result)
    assert row['binding']['class_id']=='httpx._models.Response'
    assert {(w['span']['line'],w['value']) for w in row['writers']} >= {(initialization,'False'),(closing,'True')}
    paths=[p for p in row['writer_paths'] if p['root']['method']==entry and p['writer_method']=='close']
    assert paths
    assert all(p['requires_generator_runtime_binding'] for p in paths)
    assert all(p['status']=='syntactic_path_not_execution_proof' for p in paths)
