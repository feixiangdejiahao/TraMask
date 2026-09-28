"""Independent resource lifecycle toys; no repository/evaluator fixtures."""
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.exception_contexts import ExceptionBudget, generate_exception_contexts
from relational_gap.frontend import extract_frontend, to_emitter_corpus


SUBJECT = '''import pytest
events = []
class Device:
    def __init__(self, payload, mode='source'):
        self.payload, self.mode, self.closed = payload, mode, False
        events.append(('construct', payload, mode))
    def read(self):
        try:
            if self.payload == b'bad': raise ValueError('broken-7')
            return 'ready'
        finally:
            self.closed = True
            events.append(('close', self.mode))

'''

DONOR = '''def test_bad():
    obj = Device(b'bad')
    with pytest.raises(ValueError, match=r'broken-\\d+'):
        obj.read()

'''


def corpus_for(code):
    frontend = extract_frontend([Source('test_exceptions.py', code, 'python')])
    return to_emitter_corpus(frontend), frontend


def candidates_for(corpus, frontend, name):
    test_id = next(key for key, row in corpus['tests'].items() if row['name'] == name)
    return [row for row in generate_exception_contexts(corpus, frontend)['candidates'] if row['base_test_id'] == test_id]


def namespace_for(corpus, candidate):
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    namespace = {}
    for code in output['files'].values():
        exec(compile(code, '<exception-state-witness>', 'exec'), namespace)
    return namespace, output['obligations'][0]['test_name'], output


def test_constructor_input_and_source_matcher_replace_normal_assert_and_keep_later_state_q():
    corpus, frontend = corpus_for(SUBJECT + DONOR + '''def test_state():
    receiver = Device(b'good', mode='recipient')
    assert receiver.read() == 'ready'
    assert receiver.closed is True
''')
    candidates = candidates_for(corpus, frontend, 'test_state')
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate['relation']['input_route'] == 'receiver_constructor'
    assert candidate['relation']['argument_binding']['status'] == 'source_actual_formal'
    assert candidate['edits'][0]['before'] == "b'good'" and candidate['edits'][0]['after'] == "b'bad'"
    wrapper = candidate['edits'][1]
    assert wrapper['before'] == "assert receiver.read() == 'ready'"
    assert 'pytest.raises(ValueError' in wrapper['after'] and 'broken-' in wrapper['after']
    assert wrapper['after'].count('receiver.read()') == 1
    q = next(q for q in corpus['capsules'] if q['id'] == candidate['target_capsule_id'])
    assert q['observed']['text'] == 'receiver.closed'
    assert candidate['source_observation_id'] == q['id']
    replaced = candidate['provenance']['replaced_normal_observation_ids']
    assert len(replaced) == 1 and replaced != [q['id']]
    assert wrapper['role'] == 'source_exception_context'
    assert candidate['oracle']['assertion_ids'] == [q['id']]
    namespace, test_name, _ = namespace_for(corpus, candidate)
    namespace[test_name]()
    assert namespace['events'] == [('construct', b'bad', 'recipient'), ('close', 'recipient')]
    json.dumps(candidate)


def test_invocation_formals_align_keyword_order_and_other_actuals_stay_receiving_values():
    corpus, frontend = corpus_for('''import pytest
events = []
class Device:
    def __init__(self): self.closed = False
    def accept(self, payload, count):
        self.closed = True
        events.append((payload, count))
        if payload == b'bad': raise ValueError('invalid')

def test_bad():
    source = Device()
    with pytest.raises(ValueError, match='invalid'):
        source.accept(payload=b'bad', count=1)

def test_state():
    target = Device()
    target.accept(count=7, payload=b'good')
    assert target.closed is True
''')
    candidates = candidates_for(corpus, frontend, 'test_state')
    candidate = next(row for row in candidates if row['provenance']['source_argument_span']['start_byte'] ==
                     next(a['span']['start_byte'] for c in frontend['calls'] if c['callee'] == 'source.accept'
                          for a in c['arguments'] if a['keyword'] == 'payload'))
    assert len(candidate['edits']) == 1
    assert candidate['relation']['argument_binding']['source']['slot'] == 0
    assert candidate['relation']['argument_binding']['target']['slot'] == 1
    namespace, test_name, _ = namespace_for(corpus, candidate)
    namespace[test_name]()
    assert namespace['events'] == [(b'bad', 7)]


def test_literal_alias_closure_and_receiver_aliases_preserve_source_binding_provenance():
    corpus, frontend = corpus_for(SUBJECT + '''def test_bad():
    payload = b'bad'
    alias_payload = payload
    first = Device(alias_payload)
    alias = first
    with pytest.raises(ValueError):
        alias.read()

def test_state():
    obj = Device(b'good')
    reader = obj
    reader.read()
    observer = obj
    assert observer.closed is True
''')
    candidate = candidates_for(corpus, frontend, 'test_state')[0]
    assert len(candidate['provenance']['source_literal_binding_path']) == 2
    assert candidate['provenance']['receiver_mapping'] == {'alias': 'reader'}
    assert 'alias_payload' not in candidate['edits'][0]['after']
    namespace, test_name, _ = namespace_for(corpus, candidate)
    namespace[test_name]()
    assert namespace['events'][0][1] == b'bad'


def test_try_except_preserves_source_exception_check_and_alpha_renames_catch_variable():
    corpus, frontend = corpus_for(SUBJECT + '''def test_bad():
    message = ('broken-7',)
    source = Device(b'bad')
    try:
        source.read()
    except ValueError as caught:
        assert caught.args == message
    else:
        assert False, 'source expected the exception'

def test_state():
    caught = 'recipient value'
    message = 'different local'
    receiver = Device(b'good')
    receiver.read()
    assert receiver.closed is True
    assert caught == 'recipient value'
    assert message == 'different local'
''')
    candidate = candidates_for(corpus, frontend, 'test_state')[0]
    text = candidate['edits'][-1]['after']
    assert 'except ValueError as gc_exc_' in text
    assert "('broken-7',)" in text and 'source expected the exception' in text
    assert ' == message' not in text
    assert candidate['provenance']['exception_closure']['catch_binding_renames']['caught'].startswith('gc_exc_')
    namespace, test_name, _ = namespace_for(corpus, candidate)
    namespace[test_name]()


def test_pytest_capture_alias_does_not_overwrite_recipient_local():
    corpus, frontend = corpus_for(SUBJECT + '''def test_bad():
    obj = Device(b'bad')
    with pytest.raises(ValueError, match='broken-7') as info:
        obj.read()

def test_state():
    info = 'keep'
    receiver = Device(b'good')
    receiver.read()
    assert receiver.closed is True
    assert info == 'keep'
''')
    candidate = candidates_for(corpus, frontend, 'test_state')[0]
    assert ' as gc_exc_' in candidate['edits'][-1]['after']
    namespace, test_name, _ = namespace_for(corpus, candidate)
    namespace[test_name]()


def test_missing_cleanup_effect_in_current_program_does_not_block_witness_generation():
    corpus, frontend = corpus_for('''import pytest
class Device:
    def __init__(self, payload): self.payload, self.closed = payload, False
    def read(self):
        if self.payload == b'bad': raise ValueError('broken')
        self.closed = True
        return 'ready'

def test_bad():
    source = Device(b'bad')
    with pytest.raises(ValueError):
        source.read()

def test_state():
    target = Device(b'good')
    assert target.read() == 'ready'
    assert target.closed is True
''')
    candidate = candidates_for(corpus, frontend, 'test_state')[0]
    namespace, test_name, output = namespace_for(corpus, candidate)
    for control in output['controls']:
        namespace[control['test_name']]()
    with pytest.raises(AssertionError):
        namespace[test_name]()
    assert candidate['relation']['applicability'] == 'unknown_requires_independent_admission'


def test_saved_q_is_pinned_after_invocation_but_earlier_snapshot_other_object_and_rebinding_are_not():
    corpus, frontend = corpus_for(SUBJECT + DONOR + '''def test_later_snapshot():
    receiver = Device(b'good')
    receiver.read()
    saved = receiver.closed
    assert saved is True

def test_earlier_snapshot():
    receiver = Device(b'good')
    saved = receiver.closed
    receiver.read()
    assert saved is False

def test_other_receiver():
    receiver = Device(b'good')
    other = Device(b'good')
    receiver.read()
    assert other.closed is False

def test_rebound():
    receiver = Device(b'good')
    receiver.read()
    receiver = Device(b'good')
    assert receiver.closed is False
''')
    assert candidates_for(corpus, frontend, 'test_later_snapshot')
    assert not candidates_for(corpus, frontend, 'test_earlier_snapshot')
    assert not candidates_for(corpus, frontend, 'test_other_receiver')
    assert not candidates_for(corpus, frontend, 'test_rebound')


def test_recipient_context_manager_setup_and_cleanup_remain_in_original_scope():
    corpus, frontend = corpus_for(SUBJECT + '''from contextlib import contextmanager
@contextmanager
def surrounding():
    events.append('enter')
    try: yield
    finally: events.append('leave')

''' + DONOR + '''def test_state():
    with surrounding():
        receiver = Device(b'good')
        receiver.read()
        assert receiver.closed is True
''')
    candidates = candidates_for(corpus, frontend, 'test_state')
    assert candidates, generate_exception_contexts(corpus, frontend)['skipped']
    namespace, test_name, _ = namespace_for(corpus, candidates[0])
    namespace[test_name]()
    assert namespace['events'] == ['enter', ('construct', b'bad', 'source'), ('close', 'source'), 'leave']


def test_effectful_expected_expression_and_shadowed_exception_import_are_not_captured():
    corpus, frontend = corpus_for(SUBJECT + DONOR + '''def expected(): return 'ready'

def test_effectful():
    receiver = Device(b'good')
    assert receiver.read() == expected()
    assert receiver.closed is True

def test_shadowed():
    pytest = 'recipient local'
    receiver = Device(b'good')
    receiver.read()
    assert receiver.closed is True
''')
    assert not candidates_for(corpus, frontend, 'test_effectful')
    assert not candidates_for(corpus, frontend, 'test_shadowed')
    result = generate_exception_contexts(corpus, frontend)
    assert any('exception_context_bindings_not_closed' in reason for reason in result['skipped'])


def test_different_constructor_types_do_not_align_by_member_name():
    corpus, frontend = corpus_for(SUBJECT + DONOR + '''class Other:
    def __init__(self, payload): self.closed = False
    def read(self): self.closed = True

def test_state():
    receiver = Other(b'good')
    receiver.read()
    assert receiver.closed is True
''')
    assert not candidates_for(corpus, frontend, 'test_state')


def test_unknown_input_calls_are_not_executed_or_transferred_as_closed_values():
    corpus, frontend = corpus_for(SUBJECT + '''def side_effect():
    raise RuntimeError('generation must never call this')

def test_bad():
    obj = Device(side_effect())
    with pytest.raises(ValueError):
        obj.read()

def test_state():
    receiver = Device(b'good')
    receiver.read()
    assert receiver.closed is True
''')
    result = generate_exception_contexts(corpus, frontend)
    assert not result['candidates']
    assert result['skipped']['input_expression_not_closed_literal']


def test_parent_budget_and_pinned_observations_are_deterministic():
    corpus, frontend = corpus_for(SUBJECT + DONOR + ''.join(f'''def test_{name}():
    receiver = Device(b'good')
    receiver.read()
    assert receiver.closed is True

''' for name in ['north', 'south', 'east']))
    budget = ExceptionBudget(max_candidates=3)
    result = generate_exception_contexts(corpus, frontend, budget)
    assert len(result['candidates']) == 3
    assert len({row['base_test_id'] for row in result['candidates']}) == 3
    assert len({row['target_capsule_id'] for row in result['candidates']}) == 3
    assert result['budget_exhausted']
    assert result == generate_exception_contexts(corpus, frontend, budget)


def test_invalid_budget_is_rejected():
    corpus, frontend = corpus_for(SUBJECT + DONOR)
    with pytest.raises(ValueError, match='positive integers'):
        generate_exception_contexts(corpus, frontend, ExceptionBudget(max_candidates=0))


def test_source_exception_and_framework_imports_close_across_test_files(monkeypatch):
    import sys
    import types

    production = '''class Failure(Exception): pass
class Device:
    def __init__(self, payload): self.payload, self.closed = payload, False
    def read(self):
        self.closed = True
        if self.payload == b'bad': raise Failure('broken')
'''
    sources = [Source('sample_resource.py', production, 'python'),
               Source('test_bad.py', '''import pytest as checks
from sample_resource import Device, Failure

def test_bad():
    source = Device(b'bad')
    with checks.raises(Failure, match='broken'):
        source.read()
''', 'python'),
               Source('test_state.py', '''from sample_resource import Device

def test_state():
    receiver = Device(b'good')
    receiver.read()
    assert receiver.closed is True
''', 'python')]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    candidates = candidates_for(corpus, frontend, 'test_state')
    assert candidates, generate_exception_contexts(corpus, frontend)['skipped']
    candidate = candidates[0]
    assert {row['name'] for row in candidate['imports']} == {'checks', 'Failure'}
    module = types.ModuleType('sample_resource')
    exec(production, module.__dict__)
    monkeypatch.setitem(sys.modules, 'sample_resource', module)
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    namespace = {}
    exec(output['files']['test_state.py'], namespace)
    namespace[output['obligations'][0]['test_name']]()


def test_shared_match_literal_is_closed_without_capturing_recipient_name():
    corpus, frontend = corpus_for(SUBJECT + '''def test_bad():
    pattern = r'broken-\\d+'
    source = Device(b'bad')
    with pytest.raises(ValueError, match=pattern):
        source.read()

def test_state():
    pattern = 'not the donor matcher'
    receiver = Device(b'good')
    receiver.read()
    assert receiver.closed is True
    assert pattern == 'not the donor matcher'
''')
    candidate = candidates_for(corpus, frontend, 'test_state')[0]
    assert 'match=pattern' not in candidate['edits'][-1]['after']
    assert candidate['provenance']['exception_closure']['closed_dependency_spans']
    namespace, test_name, _ = namespace_for(corpus, candidate)
    namespace[test_name]()


def test_standalone_invocation_composes_with_existing_atomic_q_selection():
    from relational_gap.atomic_observations import atomize_candidates

    corpus, frontend = corpus_for(SUBJECT + DONOR + '''def test_state():
    receiver = Device(b'good')
    receiver.read()
    assert receiver.closed is True
''')
    candidate = candidates_for(corpus, frontend, 'test_state')[0]
    atomized = atomize_candidates(corpus, frontend, [candidate])
    assert not atomized['unknowns']
    assert len(atomized['candidates']) == 1
    atomic = atomized['candidates'][0]
    assert atomic['observation_id'] == candidate['target_capsule_id']
    namespace, test_name, _ = namespace_for(corpus, atomic)
    namespace[test_name]()


def test_direct_assert_exception_wrapper_survives_atomic_observation_selection():
    from relational_gap.atomic_observations import atomize_candidates

    corpus, frontend = corpus_for(SUBJECT + DONOR + '''def test_state():
    receiver = Device(b'good')
    assert receiver.read() is None
    assert receiver.closed is True
''')
    candidate = candidates_for(corpus, frontend, 'test_state')[0]
    atomized = atomize_candidates(corpus, frontend, [candidate])
    assert not atomized['unknowns']
    atomic, = atomized['candidates']
    assert atomic['atomic_observation']['source_exception_guard_ids']
    namespace, test_name, _ = namespace_for(corpus, atomic)
    namespace[test_name]()


ITERATOR_SUBJECT = '''import pytest
events = []
class Reader:
    def __init__(self, payload):
        self.source = iter((payload,)) if isinstance(payload, bytes) else iter(payload)
        self.closed = False
    def iterate(self):
        try:
            for chunk in self.source:
                events.append(('chunk', chunk))
                if chunk == b'bad': raise ValueError('invalid chunk')
                yield chunk
        finally:
            if hasattr(self.source, 'close'): self.source.close()
            self.closed = True

'''


@pytest.mark.parametrize('consumer', ['list', 'tuple', 'next'])
def test_builtin_consumption_keeps_outer_evaluation_and_exception_timing(consumer):
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + f'''def test_bad():
    source = Reader(b'bad')
    with pytest.raises(ValueError, match='invalid chunk'):
        {consumer}(source.iterate())

def test_state():
    receiver = Reader(b'good')
    {consumer}(receiver.iterate())
    assert receiver.closed is True
''')
    candidate, = candidates_for(corpus, frontend, 'test_state')
    assert candidate['relation']['builtin_consumers'][0]['name'] == consumer
    assert candidate['edits'][-1]['after'].count(f'{consumer}(receiver.iterate())') == 1
    namespace, test_name, _ = namespace_for(corpus, candidate)
    namespace[test_name]()


@pytest.mark.parametrize('shadow', [
    'def list(value): return value\n',
    'list = tuple\n',
    'from somewhere import list\n',
    'if enabled:\n    list = tuple\n',
])
def test_module_shadowed_consumer_is_not_assumed_builtin(shadow):
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + shadow + '''def test_bad():
    source = Reader(b'bad')
    with pytest.raises(ValueError):
        list(source.iterate())

def test_state():
    receiver = Reader(b'good')
    list(receiver.iterate())
    assert receiver.closed is True
''')
    assert not candidates_for(corpus, frontend, 'test_state')


@pytest.mark.parametrize('shadow', ['list = tuple', 'from somewhere import list'])
def test_test_local_shadowed_consumer_is_not_assumed_builtin(shadow):
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + ITERATOR_DONOR + f'''def test_state():
    {shadow}
    receiver = Reader(b'good')
    list(receiver.iterate())
    assert receiver.closed is True
''')
    assert not candidates_for(corpus, frontend, 'test_state')


def test_nested_builtin_consumers_and_next_default_keep_complete_invocation():
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + ITERATOR_DONOR + '''def test_state():
    receiver = Reader(b'good')
    tuple(list(receiver.iterate()))
    assert receiver.closed is True

def test_default():
    receiver = Reader(b'good')
    next(receiver.iterate(), None)
    assert receiver.closed is True
''')
    for name, expression in [('test_state', 'tuple(list(receiver.iterate()))'),
                             ('test_default', 'next(receiver.iterate(), None)')]:
        candidate, = candidates_for(corpus, frontend, name)
        assert expression in candidate['edits'][-1]['after']
        namespace, test_name, _ = namespace_for(corpus, candidate)
        namespace[test_name]()


LOCAL_GENERATOR = '''def test_state():
    def body():
        events.append('entered')
        try:
            yield b'first'
            events.append('between')
            yield b'second'
        finally:
            events.append('producer_closed')
    receiver = Reader(body())
    assert events == []
    assert list(receiver.iterate()) == [b'first', b'second']
    assert receiver.closed is True
    assert events[-1] == 'producer_closed'
'''


ITERATOR_DONOR = '''def test_bad():
    source = Reader(b'bad')
    with pytest.raises(ValueError, match='invalid chunk'):
        list(source.iterate())

'''


def test_nested_generator_composes_each_yield_without_replacing_lazy_actual_or_other_chunks():
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + ITERATOR_DONOR + LOCAL_GENERATOR)
    candidates = candidates_for(corpus, frontend, 'test_state')
    assert len(candidates) == 2, generate_exception_contexts(corpus, frontend)['skipped']
    assert {row['edits'][0]['before'] for row in candidates} == {"b'first'", "b'second'"}
    for candidate in candidates:
        coordinate = candidate['provenance']['target_input_coordinate']
        assert coordinate['binding_status'] == 'unique_prior_direct_test_local_function'
        assert coordinate['literal_family'] == 'bytes'
        assert candidate['relation']['input_carrier'] == 'local_generator_yield'
        assert candidate['provenance']['target_argument_span'] != coordinate['span']
        namespace, test_name, output = namespace_for(corpus, candidate)
        namespace[test_name]()
        assert namespace['events'][0] == 'entered'
        assert namespace['events'][-1] == 'producer_closed'
        generated = next(text for text in output['files'].values() if test_name in text)
        assert 'Reader(body())' in generated
        assert generated.count('yield ') >= 4  # original control and both cloned yields
        if coordinate['yield_index'] == 1:
            assert namespace['events'] == ['entered', ('chunk', b'first'), 'between',
                                            ('chunk', b'bad'), 'producer_closed']
    json.dumps(candidates)


def test_generator_exception_witness_detects_missing_cleanup_while_normal_control_passes():
    broken = ITERATOR_SUBJECT.replace('''        finally:
            if hasattr(self.source, 'close'): self.source.close()
            self.closed = True''', '''        except ValueError:
            raise
        else:
            if hasattr(self.source, 'close'): self.source.close()
            self.closed = True''')
    corpus, frontend = corpus_for(broken + ITERATOR_DONOR + LOCAL_GENERATOR)
    candidate = candidates_for(corpus, frontend, 'test_state')[1]
    namespace, test_name, output = namespace_for(corpus, candidate)
    for control in output['controls']:
        namespace['events'].clear()
        namespace[control['test_name']]()
    namespace['events'].clear()
    with pytest.raises(AssertionError):
        namespace[test_name]()


@pytest.mark.parametrize('replacement,reason', [
    ("yield b'first'", None),
    ("yield 'first'", 'generator_source_literal_family_mismatch'),
    ('yield get_chunk()', 'generator_yield_not_closed_literal'),
    ("yield from [b'first']", 'generator_delegated_yield_not_supported'),
])
def test_generator_coordinate_requires_pure_type_compatible_yield(replacement, reason):
    body = LOCAL_GENERATOR.replace("yield b'first'", replacement).replace("yield b'second'", replacement)
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + ITERATOR_DONOR + body)
    result = generate_exception_contexts(corpus, frontend)
    if reason is None:
        assert result['candidates']
    else:
        assert not result['candidates']
        assert result['skipped'][reason]


@pytest.mark.parametrize('change', ['parameters', 'reassignment', 'decorator', 'global_definition'])
def test_generator_coordinate_requires_unambiguous_plain_test_local_binding(change):
    code = ITERATOR_SUBJECT + ITERATOR_DONOR + LOCAL_GENERATOR
    if change == 'parameters':
        code = code.replace('def body():', 'def body(x=1):')
    elif change == 'reassignment':
        code = code.replace('    receiver = Reader(body())', '    body = replacement\n    receiver = Reader(body())')
    elif change == 'decorator':
        code = code.replace('    def body():', '    @decorate\n    def body():')
    else:
        code = code.replace('def test_state():\n    def body():', 'def body():').replace(
            "    receiver = Reader(body())", "\ndef test_state():\n    receiver = Reader(body())")
        code = code.replace("        events.append('entered')", "    events.append('entered')")
        start, end = code.index('        try:', code.index('def body():')), code.index('\ndef test_state():')
        code = code[:start] + '\n'.join(line[4:] for line in code[start:end].split('\n')) + code[end:]
    corpus, frontend = corpus_for(code)
    assert not candidates_for(corpus, frontend, 'test_state')


ASSIGNED_SUBJECT = '''import pytest
events = []
class Envelope:
    def __init__(self, items):
        self.items = items
        events.append('factory')
    def __iter__(self): return iter(self.items)
class Resource:
    def __init__(self, content=None, stream=None):
        self.source = iter((content,)) if stream is None else iter(stream)
        self.closed = False
    def iterate(self):
        try:
            for chunk in self.source:
                events.append(('chunk', chunk))
                if chunk.startswith(b'bad'): raise ValueError('invalid')
                yield chunk
        finally:
            if hasattr(self.source, 'close'): self.source.close()
            self.closed = True

def test_bad():
    source = Resource(content=b'bad!xxxx')
    with pytest.raises(ValueError, match='invalid'):
        list(source.iterate())

'''


CAPTURED_RECIPIENT = '''def test_state():
    payload = b'abcdwxyz'
    def produce():
        events.append('entered')
        try:
            for offset in range(0, len(payload), 4):
                yield payload[offset:offset+4]
        finally:
            events.append('producer_closed')
    receiver = Resource(stream=Envelope(produce()))
    assert events == ['factory']
    parts = list(receiver.iterate())
    assert len(parts) == 2
    assert receiver.closed is True
    assert events[-1] == 'producer_closed'
'''


def test_assignment_keeps_normal_result_check_behind_completion_flag_and_retains_resource_q():
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + ITERATOR_DONOR + '''def test_state():
    receiver = Reader(b'good')
    parts = list(receiver.iterate())
    assert len(parts) == 1
    assert receiver.closed is True
''')
    candidate, = candidates_for(corpus, frontend, 'test_state')
    assert candidate['provenance']['normal_result_guard']['binding'] == 'parts'
    flag = candidate['provenance']['normal_result_guard']['completion_flag']
    guard = next(e for e in candidate['edits'] if e.get('role') == 'source_exception_context')
    assert flag + ' = False' in guard['after'] and flag + ' = True' in guard['after']
    assert 'parts = list(receiver.iterate())' in guard['after']
    check = next(e for e in candidate['edits'] if e.get('role') == 'source_normal_result_guard')
    assert check['before'] == 'assert len(parts) == 1'
    assert check['after'].startswith('if ' + flag + ':')
    namespace, test_name, output = namespace_for(corpus, candidate)
    for control in output['controls']:
        namespace[control['test_name']]()
    namespace[test_name]()


@pytest.mark.parametrize('broken', [False, True])
def test_nested_factory_capture_slice_preserves_source_normal_control_and_detects_exception_cleanup(broken):
    from relational_gap.atomic_observations import atomize_candidates
    subject = ASSIGNED_SUBJECT
    if broken:
        subject = subject.replace('''        finally:
            if hasattr(self.source, 'close'): self.source.close()
            self.closed = True''', '''        except ValueError:
            raise
        else:
            if hasattr(self.source, 'close'): self.source.close()
            self.closed = True''')
    corpus, frontend = corpus_for(subject + CAPTURED_RECIPIENT)
    candidate, = candidates_for(corpus, frontend, 'test_state')
    assert candidate['relation']['input_carrier'] == 'local_generator_capture'
    assert candidate['relation']['leaf_alignment_status'] == 'unresolved_different_constructor_arguments'
    assert candidate['relation']['argument_binding']['source_keyword'] == 'content'
    assert candidate['relation']['argument_binding']['target_keyword'] == 'stream'
    assert candidate['edits'][0]['before'] == "b'abcdwxyz'"
    assert candidate['edits'][0]['after'] == "b'bad!xxxx'"
    coordinate = candidate['provenance']['target_input_coordinate']
    assert len(coordinate['factory_path']) == 1
    assert coordinate['capture_binding_path']
    assert 'payload[offset:offset+4]' not in [edit['before'] for edit in candidate['edits']]
    atomic = atomize_candidates(corpus, frontend, [candidate])
    assert not atomic['unknowns'], atomic['unknowns']
    atomic_candidate, = atomic['candidates']
    assert atomic_candidate['atomic_observation']['source_normal_result_guard_ids']
    namespace, test_name, output = namespace_for(corpus, atomic_candidate)
    for control in output['controls']:
        namespace['events'].clear()
        namespace[control['test_name']]()
        if control['base_test_id'] == candidate['base_test_id']:
            assert namespace['events'].count('factory') == 1
            assert namespace['events'][-1] == 'producer_closed'
    namespace['events'].clear()
    if broken:
        with pytest.raises(AssertionError):
            namespace[test_name]()
    else:
        namespace[test_name]()
        assert namespace['events'] == ['factory', 'entered', ('chunk', b'bad!'), 'producer_closed']
    rendered = output['files']['test_exceptions.py']
    assert 'Resource(stream=Envelope(produce()))' in rendered
    assert 'for offset in range(0, len(payload), 4):' in rendered
    assert 'yield payload[offset:offset+4]' in rendered
    json.dumps(atomic_candidate)


@pytest.mark.parametrize('dependent', [
    'use(parts)', 'copy = parts', 'assert callback(parts)', 'assert parts[0] == 1',
])
def test_assignment_rejects_result_dependent_actions_aliases_and_unknown_element_effects(dependent):
    code = ITERATOR_SUBJECT + ITERATOR_DONOR + f'''def test_state():
    receiver = Reader(b'good')
    parts = list(receiver.iterate())
    {dependent}
    assert receiver.closed is True
'''
    corpus, frontend = corpus_for(code)
    assert not candidates_for(corpus, frontend, 'test_state')


def test_generator_capture_reassignment_before_consumption_is_not_fixed_to_creation_value():
    code = ASSIGNED_SUBJECT + CAPTURED_RECIPIENT.replace("    parts = list(receiver.iterate())", "    payload = b'laterxxx'\n    parts = list(receiver.iterate())")
    corpus, frontend = corpus_for(code)
    result = generate_exception_contexts(corpus, frontend)
    assert not result['candidates']
    assert result['skipped']['generator_capture_changes_before_consumption']


def test_generator_capture_mutated_by_producer_is_not_assumed_closed():
    code = ASSIGNED_SUBJECT + CAPTURED_RECIPIENT.replace("        events.append('entered')", "        nonlocal payload\n        payload = b'laterxxx'\n        events.append('entered')")
    corpus, frontend = corpus_for(code)
    assert not candidates_for(corpus, frontend, 'test_state')


def test_assignment_result_check_outside_original_with_scope_is_guarded():
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + 'from contextlib import nullcontext\n' + ITERATOR_DONOR + '''def test_state():
    receiver = Reader(b'good')
    with nullcontext():
        parts = list(receiver.iterate())
    assert len(parts) == 1
    assert receiver.closed is True
''')
    candidate, = candidates_for(corpus, frontend, 'test_state')
    assert candidate['provenance']['normal_result_guard_ids']
    namespace, test_name, _ = namespace_for(corpus, candidate)
    namespace[test_name]()


def test_conditional_result_rebinding_does_not_leave_unguarded_unbound_checks():
    corpus, frontend = corpus_for(ITERATOR_SUBJECT + ITERATOR_DONOR + '''def test_state():
    receiver = Reader(b'good')
    parts = list(receiver.iterate())
    if condition:
        parts = []
    assert len(parts) == 1
    assert receiver.closed is True
''')
    assert not candidates_for(corpus, frontend, 'test_state')
