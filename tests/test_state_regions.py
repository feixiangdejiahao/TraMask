"""Invented regions only; source parsing and insertion never execute subjects."""
import ast

import pytest

from experimental.semantic_transport.state_contexts import generate_state_contexts
from experimental.state_regions import generate_state_regions
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit


BOX = '''class Box:
    def __init__(self): self.value = 0
    def add(self, amount): self.value += amount
    def read(self): return self.value

'''


def corpus_for(tmp_path, code):
    (tmp_path / 'test_regions.py').write_text(code)
    return build_corpus(tmp_path, 'python')


def edited(corpus, candidate):
    edit = candidate['edits'][0]
    position = edit['span']
    raw = corpus['sources'][position['path']]['code'].encode()
    assert edit['before'] == '' and position['start_byte'] == position['end_byte']
    return (raw[:position['start_byte']] + edit['after'].encode() + raw[position['end_byte']:]).decode()


@pytest.mark.parametrize('asynchronous', [False, True])
def test_context_manager_regions_keep_scope_and_insert_before_snapshot(tmp_path, asynchronous):
    prefix = 'async ' if asynchronous else ''
    code = BOX + prefix + '''def test_donor():
    def unrelated_helper(): return 99
    ''' + prefix + '''with manager() as resource:
        obj = Box()
        amount = 3
        alias = obj
        alias.add(amount)
        assert obj.read() == 3

''' + prefix + '''def test_target():
    ''' + prefix + '''with manager() as other_resource:
        receiver = Box()
        receiver.add(2)
        actual = receiver.read()
        assert actual == 2
'''
    corpus = corpus_for(tmp_path, code)
    original = generate_state_contexts(corpus)
    assert original['candidates'] == []
    assert original['skipped']['control_or_nested_scope_requires_region_analysis']
    generated = generate_state_regions(corpus)
    candidate = next(row for row in generated['candidates']
                     if corpus['tests'][row['base_test_id']]['name'] == 'test_target')
    assert candidate['arg_values'] == [3]
    assert candidate['provenance']['frontend'] == 'state_regions'
    assert len(candidate['provenance']['recipient_region']['context']) == 1
    assert candidate['provenance']['observation_state_witnesses']
    assert 'manager' not in candidate['edits'][0]['after']
    changed = edited(corpus, candidate)
    target = changed.split('def test_target():', 1)[1]
    assert target.index('receiver.add(2)') < target.index('receiver.add(gc_ctx_') < target.index('actual = receiver.read()')
    assert prefix + 'with manager() as other_resource:' in target
    ast.parse(changed)
    assert not emit(corpus, [candidate])['unsupported']
    assert generated == generate_state_regions(corpus)


def test_one_local_class_declaration_can_supply_two_independent_regions(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_scenarios():
    class Local:
        def __init__(self): self.value = 0
        def add(self, amount): self.value += amount
        def read(self): return self.value
    def unrelated_helper(): return 99
    with manager():
        first = Local()
        first.add(4)
        assert first.read() == 4
    with manager():
        second = Local()
        actual = second.read()
        assert actual == 0
''')
    assert generate_state_contexts(corpus)['candidates'] == []
    result = generate_state_regions(corpus)
    assert len(result['candidates']) == 1, result['skipped']
    candidate = result['candidates'][0]
    assert candidate['source_test_ids'] == [candidate['base_test_id']]
    assert candidate['provenance']['producer_identity'][0] == 'lexical_declaration'
    assert candidate['provenance']['receiver_mapping'] == {'first': 'second'}
    assert 'second.add(4)' in candidate['edits'][0]['after']
    assert 'class Local' not in candidate['edits'][0]['after']
    changed = edited(corpus, candidate)
    assert changed.count('class Local:') == 1
    assert changed.count('def unrelated_helper():') == 1
    assert changed.index('second.add(4)') < changed.index('actual = second.read()')
    ast.parse(changed)
    assert not emit(corpus, [candidate])['unsupported']


def test_distinct_local_classes_are_not_merged_by_name_or_same_source_text(tmp_path):
    declaration = '''    class Local:
        def __init__(self): self.value = 0
        def add(self, amount): self.value += amount
        def read(self): return self.value
'''
    code = 'def test_donor():\n' + declaration + '''    obj = Local()
    obj.add(3)
    assert obj.read() == 3

def test_target():
''' + declaration + '''    obj = Local()
    assert obj.read() == 0
'''
    corpus = corpus_for(tmp_path, code)
    assert generate_state_contexts(corpus)['candidates'] == []
    assert generate_state_regions(corpus)['candidates'] == []


def test_local_helper_does_not_hide_later_straight_line_region(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    def ignored(): return 4
    if enabled:
        unrelated()
    obj = Box()
    obj.add(5)
    assert obj.read() == 5

def test_target():
    obj = Box()
    assert obj.read() == 0
''')
    assert generate_state_contexts(corpus)['candidates'] == []
    result = generate_state_regions(corpus)
    assert len(result['candidates']) == 1
    candidate = result['candidates'][0]
    assert candidate['arg_values'] == [5]
    assert 'ignored' not in candidate['edits'][0]['after']
    assert 'unrelated' not in candidate['edits'][0]['after']
    assert not emit(corpus, [candidate])['unsupported']


def test_receiver_definition_outside_region_is_explicitly_unclosed(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    with manager():
        obj.add(3)
        assert obj.read() == 3

def test_target():
    obj = Box()
    assert obj.read() == 0
''')
    result = generate_state_regions(corpus)
    assert result['candidates'] == []
    assert result['skipped']['region_receiver_dependency_not_closed']


def test_plain_regions_are_not_generated_twice(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    obj.add(3)
    assert obj.read() == 3

def test_target():
    obj = Box()
    assert obj.read() == 0
''')
    assert generate_state_contexts(corpus)['candidates']
    result = generate_state_regions(corpus)
    assert result['candidates'] == [] and result['attempts'] == 0


@pytest.mark.parametrize('expression', ['alias.add(amount)', 'list(alias.consume(amount))',
                                       'wrap(list(alias.consume(amount)))'])
def test_call_assignment_discards_only_binding_and_preserves_complete_rhs(tmp_path, expression):
    code = '''events = []
class Box:
    def __init__(self): self.value = 0
    def add(self, amount):
        self.value += amount
        events.append(amount)
        return self.value
    def consume(self, amount):
        self.add(amount)
        yield self.value
    def read(self): return self.value
def wrap(values):
    events.append("wrapped")
    return tuple(values)

def test_donor():
    obj = Box()
    alias = obj
    amount = 3
    saved = ''' + expression + '''
    assert obj.read() == 3

def test_target():
    receiver = Box()
    actual = receiver.read()
    assert actual == 0
'''
    corpus = corpus_for(tmp_path, code)
    assert generate_state_contexts(corpus)['candidates'] == []
    generated = generate_state_regions(corpus)
    candidate = next(row for row in generated['candidates']
                     if corpus['tests'][row['base_test_id']]['name'] == 'test_target')
    inserted = candidate['edits'][0]['after']
    assert 'saved' not in inserted and 'alias' not in inserted
    assert candidate['arg_values'] == [3]
    assert candidate['provenance']['discarded_result_bindings'] == ['saved']
    assert candidate['provenance']['receiver_mapping'] == {'alias': 'receiver'}
    assert candidate['provenance']['observation_state_witnesses']
    if expression.startswith('list'):
        assert 'list(receiver.consume(' in inserted
    if expression.startswith('wrap'):
        assert 'wrap(list(receiver.consume(' in inserted
    changed = edited(corpus, candidate)
    target = changed.split('def test_target():', 1)[1]
    assert target.index(inserted.strip().splitlines()[-1].strip()) < target.index('actual = receiver.read()')
    assert not emit(corpus, [candidate])['unsupported']
    # This is only the self-contained invented program. Executing its target
    # proves generator consumption and wrapper evaluation were preserved;
    # oracle completion is deliberately outside this front end.
    namespace = {}
    exec(compile(changed, '<invented-region-toy>', 'exec'), namespace)
    with pytest.raises(AssertionError):
        namespace['test_target']()
    assert namespace['events'] == ([3, 'wrapped'] if expression.startswith('wrap') else [3])


@pytest.mark.parametrize('operation', ['saved = unknown(obj.add(3))', 'saved = obj.add(missing)'])
def test_rhs_external_callees_and_arguments_must_be_closed(tmp_path, operation):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    ''' + operation + '''
    assert obj.read() == 3

def test_target():
    obj = Box()
    assert obj.read() == 0
''')
    assert generate_state_regions(corpus)['candidates'] == []


def test_return_value_dependency_is_not_transferred_after_discarding_result(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    saved = obj.add(3)
    obj.add(saved)
    assert obj.read() == 3

def test_target():
    obj = Box()
    assert obj.read() == 0
''')
    generated = generate_state_regions(corpus)
    assert generated['candidates']
    assert generated['skipped']['missing_literal_dependency']
    assert all('saved' not in row['edits'][0]['after'] for row in generated['candidates'])
    assert all(row['provenance']['operation_count'] == 1 for row in generated['candidates'])


def test_pure_assignment_without_receiver_call_is_not_a_state_operation(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    saved = 2 + 3
    values = list([1, 2])
    assert obj.read() == 0

def test_target():
    obj = Box()
    assert obj.read() == 0
''')
    assert generate_state_regions(corpus)['candidates'] == []


def test_builtin_wrapper_cannot_be_shadowed_in_other_recipient_region(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    saved = list(obj.add(3))
    assert obj.read() == 3

def test_target():
    with manager():
        obj = Box()
        assert obj.read() == 0
    list = unknown
''')
    generated = generate_state_regions(corpus)
    assert generated['candidates'] == []
    assert generated['skipped']['rhs_builtin_shadowed_at_target']


@pytest.mark.parametrize('target', [
    '    with manager() as list:\n        obj = Box()\n        assert obj.read() == 0\n',
    '    obj = Box()\n    assert obj.read() == 0\n    for list in []:\n        pass\n',
    '    obj = Box()\n    assert obj.read() == 0\n    with manager():\n        import other as list\n',
])
def test_builtin_wrapper_checks_all_python_binding_forms(tmp_path, target):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    saved = list(obj.add(3))
    assert obj.read() == 3

def test_target():
''' + target)
    generated = generate_state_regions(corpus)
    assert generated['candidates'] == []
    assert any(generated['skipped'].get(reason) for reason in (
        'rhs_builtin_shadowed_at_target', 'rhs_external_callee_shadowed_at_target'))


def test_resolved_external_wrapper_cannot_be_rebound_in_other_region(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def wrap(value): return value
def test_donor():
    obj = Box()
    saved = wrap(obj.add(3))
    assert obj.read() == 3

def test_target():
    obj = Box()
    assert obj.read() == 0
    with manager():
        wrap = unknown
''')
    generated = generate_state_regions(corpus)
    assert generated['candidates'] == []
    assert generated['skipped']['rhs_external_callee_shadowed_at_target']


def test_multiline_rhs_literal_cannot_change_indentation_during_rendering(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    saved = obj.add("""a
        b""")
    assert obj.read() == 3

def test_target():
    obj = Box()
    assert obj.read() == 0
''')
    generated = generate_state_regions(corpus)
    assert generated['candidates'] == []
    assert generated['skipped']['rhs_multiline_literal_requires_byte_preserving_renderer']


def test_multiline_literal_dependency_cannot_be_reindented_into_deeper_region(tmp_path):
    corpus = corpus_for(tmp_path, BOX + '''def test_donor():
    obj = Box()
    amount = """a
        b"""
    saved = obj.add(amount)
    assert obj.read() == 3

def test_target():
    with manager():
        obj = Box()
        assert obj.read() == 0
''')
    generated = generate_state_regions(corpus)
    assert generated['candidates'] == []
    assert generated['skipped']['literal_closure_multiline_string_requires_byte_preserving_renderer']
