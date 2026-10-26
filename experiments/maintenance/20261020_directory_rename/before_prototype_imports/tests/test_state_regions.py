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


def corpus_for(tmp_path, code, language='python'):
    filename = {'python': 'test_regions.py', 'go': 'regions_test.go', 'typescript': 'regions.test.ts'}[language]
    (tmp_path / filename).write_text(code)
    return build_corpus(tmp_path, language)


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


GO_BOX = '''package toy
import "testing"
type Box struct { value int }
func NewBox() *Box { return &Box{} }
func Put(amount int, box *Box) { box.value += amount }
func (box *Box) Read() int { return box.value }
'''


def test_go_control_and_local_callback_do_not_hide_later_straight_line_region(tmp_path):
    corpus = corpus_for(tmp_path, GO_BOX + '''func TestDonor(t *testing.T) {
    if false { t.Log("unrelated") }
    callback := func() { t.Log("unused") }
    _ = callback
    obj := NewBox()
    amount := 3
    copied := amount
    alias := obj
    Put(copied, alias)
    if obj.Read() != 3 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
    receiver := NewBox()
    actual := receiver.Read()
    if actual != 0 { t.Fatal("wrong") }
}
''', 'go')
    assert generate_state_contexts(corpus)['candidates'] == []
    result = generate_state_regions(corpus)
    candidate = next(row for row in result['candidates']
                     if corpus['tests'][row['base_test_id']]['name'] == 'TestTarget')
    assert candidate['language'] == 'go'
    assert candidate['arg_values'] == [3]
    assert candidate['provenance']['receiver_mapping'] == {'alias': 'receiver'}
    assert candidate['provenance']['observation_state_witnesses']
    inserted = candidate['edits'][0]['after']
    assert 'Put(' in inserted and ', receiver)' in inserted
    assert 'NewBox' not in inserted and 'callback' not in inserted
    changed = edited(corpus, candidate)
    assert changed.index(inserted.strip()) < changed.index('actual := receiver.Read()')
    assert not emit(corpus, [candidate])['unsupported']


def test_go_explicit_block_regions_keep_original_assertion_guards(tmp_path):
    corpus = corpus_for(tmp_path, GO_BOX + '''func TestBlocks(t *testing.T) {
    {
        obj := NewBox()
        Put(4, obj)
        if obj.Read() != 4 { t.Fatal("wrong") }
    }
    {
        receiver := NewBox()
        actual := receiver.Read()
        if actual != 0 { t.Fatal("wrong") }
    }
}
''', 'go')
    assert generate_state_contexts(corpus)['candidates'] == []
    result = generate_state_regions(corpus)
    candidate = next(row for row in result['candidates'] if row['arg_values'] == [4])
    assert candidate['source_test_ids'] == [candidate['base_test_id']]
    assert len(candidate['provenance']['recipient_region']['context']) == 1
    assert 'Put(4, receiver)' in candidate['edits'][0]['after']
    assert not emit(corpus, [candidate])['unsupported']


def test_go_cross_region_local_callee_shadow_stays_unknown(tmp_path):
    corpus = corpus_for(tmp_path, GO_BOX + '''func TestDonor(t *testing.T) {
    Put := func(amount int, box *Box) { box.value = amount }
    if false { t.Log("unrelated") }
    obj := NewBox()
    Put(4, obj)
    if obj.Read() != 4 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
    receiver := NewBox()
    if receiver.Read() != 0 { t.Fatal("wrong") }
}
''', 'go')
    assert generate_state_regions(corpus)['candidates'] == []


def test_go_callback_subtests_are_explicitly_outside_available_capsules(tmp_path):
    corpus = corpus_for(tmp_path, GO_BOX + '''func TestNested(t *testing.T) {
    t.Run("donor", func(t *testing.T) {
        obj := NewBox()
        Put(4, obj)
        if obj.Read() != 4 { t.Fatal("wrong") }
    })
    t.Run("target", func(t *testing.T) {
        obj := NewBox()
        if obj.Read() != 0 { t.Fatal("wrong") }
    })
}
''', 'go')
    assert corpus['capsules'] == []
    generated = generate_state_regions(corpus)
    assert generated['candidates'] == []
    assert generated['skipped']['no_observation_capsule']


def test_typescript_regions_and_shorthand_literal_closure_preserve_property_keys(tmp_path):
    corpus = corpus_for(tmp_path, '''import { Box } from './box';
describe('scope', () => {
    it('donor', () => {
        if (condition) { unrelated(); }
        class Unused {}
        const obj = new Box();
        const amount = 3;
        const nested = {amount};
        const options = {nested, fixed: true};
        const alias = obj;
        alias.add(options);
        expect(obj.read()).toEqual(3);
    });
    it('target', () => {
        const callback = () => 9;
        const receiver = new Box();
        const actual = receiver.read();
        expect(actual).toEqual(0);
    });
});
''', 'typescript')
    assert generate_state_contexts(corpus)['candidates'] == []
    generated = generate_state_regions(corpus)
    candidate = next(row for row in generated['candidates']
                     if corpus['tests'][row['base_test_id']]['name'] == 'target')
    assert candidate['language'] == 'typescript'
    assert candidate['arg_values'] == [{'nested': {'amount': 3}, 'fixed': True}]
    inserted = candidate['edits'][0]['after']
    assert 'amount: gc_ctx_' in inserted and 'nested: gc_ctx_' in inserted
    assert 'receiver.add(gc_ctx_' in inserted
    assert 'new Box' not in inserted and 'callback' not in inserted and 'Unused' not in inserted
    assert candidate['provenance']['observation_state_witnesses']
    assert not emit(corpus, [candidate])['unsupported']


def test_typescript_explicit_blocks_keep_same_lexical_class_identity(tmp_path):
    corpus = corpus_for(tmp_path, '''it('scenarios', () => {
    class Local {
        value = 0;
        add(n) { this.value += n; }
        read() { return this.value; }
    }
    {
        const obj = new Local();
        obj.add(2);
        expect(obj.read()).toEqual(2);
    }
    {
        const receiver = new Local();
        expect(receiver.read()).toEqual(0);
    }
});
''', 'typescript')
    assert generate_state_contexts(corpus)['candidates'] == []
    generated = generate_state_regions(corpus)
    candidate = next(row for row in generated['candidates'] if row['arg_values'] == [2])
    assert candidate['provenance']['producer_identity'][0] == 'lexical_declaration'
    assert 'receiver.add(2)' in candidate['edits'][0]['after']
    assert len(candidate['provenance']['recipient_region']['context']) == 1
    assert not emit(corpus, [candidate])['unsupported']


def test_typescript_unknown_shorthand_dependency_is_not_invented(tmp_path):
    corpus = corpus_for(tmp_path, '''import { Box } from './box';
it('donor', () => {
    if (noise) { unrelated(); }
    const obj = new Box();
    obj.add({missing});
    expect(obj.read()).toEqual(1);
});
it('target', () => {
    const obj = new Box();
    expect(obj.read()).toEqual(0);
});
''', 'typescript')
    generated = generate_state_regions(corpus)
    assert generated['candidates'] == []
    assert generated['skipped']['missing_literal_dependency']


def test_go_plain_assertion_guards_do_not_duplicate_core_contexts(tmp_path):
    corpus = corpus_for(tmp_path, GO_BOX + '''func TestDonor(t *testing.T) {
    obj := NewBox()
    Put(4, obj)
    if obj.Read() != 4 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
    receiver := NewBox()
    if receiver.Read() != 0 { t.Fatal("wrong") }
}
''', 'go')
    assert generate_state_contexts(corpus)['candidates']
    generated = generate_state_regions(corpus)
    assert generated['candidates'] == [] and generated['attempts'] == 0


@pytest.mark.parametrize('discard_return', [False, True])
def test_go_region_emission_compiles_without_unused_transplanted_bindings(tmp_path, discard_return):
    import os
    import shutil
    import subprocess
    executable = shutil.which('go')
    if executable is None:
        pytest.skip('Go compiler unavailable')
    operation = ('saved, err := Update(alias, copied)\n    _ = saved\n    _ = err'
                 if discard_return else 'Put(copied, alias)')
    corpus = corpus_for(tmp_path, GO_BOX + '''func Update(box *Box, amount int) (int, error) { box.value += amount; return box.value, nil }
func TestDonor(t *testing.T) {
    if false { t.Log("unrelated") }
    obj := NewBox()
    amount := 3
    copied := amount
    alias := obj
    ''' + operation + '''
    if obj.Read() != 3 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
    receiver := NewBox()
    actual := receiver.Read()
    if actual != 0 { t.Fatal("wrong") }
}
''', 'go')
    candidate = next(row for row in generate_state_regions(corpus)['candidates']
                     if corpus['tests'][row['base_test_id']]['name'] == 'TestTarget')
    emitted = emit(corpus, [candidate])
    assert not emitted['unsupported']
    for filename, code in emitted['files'].items():
        (tmp_path / filename).write_text(code)
    environment = dict(os.environ, GO111MODULE='off', GOPROXY='off', GOTOOLCHAIN='local',
                       GOCACHE=str(tmp_path / 'go-cache'))
    process = subprocess.run([executable, 'test', '-run', '^$'], cwd=tmp_path, env=environment,
                             capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr


@pytest.mark.parametrize('language, code, target, expected_call', [
    ('go', GO_BOX + '''func Update(box *Box, amount int) (int, error) { box.value += amount; return box.value, nil }
func TestDonor(t *testing.T) {
    obj := NewBox()
    saved, err := Update(obj, 3)
    _ = saved
    _ = err
    if obj.Read() != 3 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
    receiver := NewBox()
    actual := receiver.Read()
    if actual != 0 { t.Fatal("wrong") }
}
''', 'TestTarget', 'Update(receiver, 3)'),
    ('typescript', '''import { Box } from './box';
it('donor', () => {
    const obj = new Box();
    const amount = 3;
    const saved = obj.update({amount});
    expect(obj.read()).toEqual(3);
});
it('target', () => {
    const receiver = new Box();
    const actual = receiver.read();
    expect(actual).toEqual(0);
});
''', 'target', 'receiver.update({amount: gc_ctx_'),
])
def test_go_and_typescript_return_assignment_preserves_rhs_and_drops_binding(tmp_path, language, code, target, expected_call):
    corpus = corpus_for(tmp_path, code, language)
    assert generate_state_contexts(corpus)['candidates'] == []
    generated = generate_state_regions(corpus)
    candidate = next(row for row in generated['candidates']
                     if corpus['tests'][row['base_test_id']]['name'] == target)
    inserted = candidate['edits'][0]['after']
    assert expected_call in inserted
    assert 'saved' not in inserted and 'err' not in inserted
    assert candidate['provenance']['discarded_result_bindings']
    assert candidate['provenance']['observation_state_witnesses']
    if language == 'typescript':
        assert inserted.rstrip().endswith(';')
        assert candidate['arg_values'] == [{'amount': 3}]
    else:
        assert candidate['arg_values'] == [3]
    assert not emit(corpus, [candidate])['unsupported']


def test_typescript_regions_do_not_cross_distinct_outer_test_scopes(tmp_path):
    corpus = corpus_for(tmp_path, '''import { Box } from './box';
describe('first', () => {
    it('donor', () => {
        if (noise) { unrelated(); }
        const obj = new Box();
        obj.add(3);
        expect(obj.read()).toEqual(3);
    });
});
describe('second', () => {
    it('target', () => {
        const obj = new Box();
        expect(obj.read()).toEqual(0);
    });
});
''', 'typescript')
    assert generate_state_regions(corpus)['candidates'] == []


def test_go_multi_return_rebinding_cannot_keep_old_receiver_identity(tmp_path):
    corpus = corpus_for(tmp_path, GO_BOX + '''func Replace(box *Box) (*Box, error) { return NewBox(), nil }
func TestDonor(t *testing.T) {
    obj := NewBox()
    var err error
    obj, err = Replace(obj)
    _ = err
    Put(3, obj)
    if obj.Read() != 3 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
    receiver := NewBox()
    if receiver.Read() != 0 { t.Fatal("wrong") }
}
''', 'go')
    assert generate_state_contexts(corpus)['candidates'] == []
    assert generate_state_regions(corpus)['candidates'] == []
