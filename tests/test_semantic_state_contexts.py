"""Independent invented programs for source-only state-context extraction."""
import os
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from prototypes.test_action_and_oracle_transfer import state_contexts
from prototypes.test_action_and_oracle_transfer.state_contexts import generate_state_contexts
from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit


PYTHON_BOX = '''class Box:
    def __init__(self): self.value = 0
    def add(self, amount): self.value += amount
    def combine(self, other, amount): self.value += other.value + amount
    def read(self): return self.value

'''


def corpus_for(tmp_path, code, language='python'):
    filename = {'python': 'test_context.py', 'go': 'context_test.go', 'typescript': 'context.test.ts'}[language]
    (tmp_path / filename).write_text(code)
    return build_corpus(tmp_path, language)


def for_target(corpus, result, name='test_target'):
    return [candidate for candidate in result['candidates']
            if corpus['tests'][candidate['base_test_id']]['name'] == name]


def changed_source(corpus, candidate):
    edit = candidate['edits'][0]
    position = edit['span']
    raw = corpus['sources'][position['path']]['code'].encode()
    assert raw[position['start_byte']:position['end_byte']].decode() == edit['before']
    return (raw[:position['start_byte']] + edit['after'].encode() + raw[position['end_byte']:]).decode()


def test_aliases_share_one_recipient_object_and_literal_closure_is_alpha_named(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
    amount = 3
    copied = amount
    first = obj
    second = first
    first.combine(second, copied)
    assert obj.read() == 3

def test_target():
    amount = 90
    receiver = Box()
    actual = receiver.read()
    assert actual == 0
''')
    result = generate_state_contexts(corpus)
    candidates = for_target(corpus, result)
    assert len(candidates) == 1
    candidate = candidates[0]
    text = candidate['edits'][0]['after']
    renames = candidate['provenance']['literal_binding_renames']
    assert set(renames) == {'amount', 'copied'}
    assert renames['amount'] != 'amount'
    assert f"{renames['copied']} = {renames['amount']}" in text
    assert f"receiver.combine(receiver, {renames['copied']})" in text
    assert 'Box()' not in text and 'first' not in text and 'second' not in text
    assert candidate['arg_values'] == [3]
    assert candidate['provenance']['receiver_mapping'] == {'first': 'receiver', 'second': 'receiver'}
    assert candidate['provenance']['observation_state_witnesses']
    assert 'oracle' not in candidate
    emitted = emit(corpus, [candidate])
    assert not emitted['unsupported']
    assert 'amount = 90' in changed_source(corpus, candidate)


def test_insertion_precedes_snapshot_evaluation_and_keeps_recipient_operations(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
    obj.add(7)
    assert obj.read() == 7

def test_target():
    receiver = Box()
    receiver.add(2)
    actual = receiver.read()
    receiver.add(5)
    assert actual == 2
''')
    candidate = for_target(corpus, generate_state_contexts(corpus))[0]
    edited = changed_source(corpus, candidate).split('def test_target():', 1)[1]
    assert edited.index('receiver.add(2)') < edited.index('receiver.add(7)')
    assert edited.index('receiver.add(7)') < edited.index('actual = receiver.read()')
    assert edited.index('actual = receiver.read()') < edited.index('receiver.add(5)')
    assert 'assert actual == 2' in edited


def test_each_observation_uses_its_own_evaluation_point(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
    obj.add(7)
    assert obj.read() == 7

def test_target():
    receiver = Box()
    before = receiver.read()
    assert before == 0
    receiver.add(2)
    after = receiver.read()
    assert after == 2
''')
    capsule = next(row for row in corpus['capsules'] if row['observed']['text'] == 'after')
    candidate = next(row for row in for_target(corpus, generate_state_contexts(corpus))
                     if row['target_capsule_id'] == capsule['id'] and row['arg_values'] == [7])
    edited = changed_source(corpus, candidate).split('def test_target():', 1)[1]
    assert edited.index('receiver.add(2)') < edited.index('receiver.add(7)') < edited.index('after = receiver.read()')
    assert 'assert before == 0' in edited  # Oracle atomicization belongs to the caller.


def test_one_to_three_ordered_operations_are_offered(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
    obj.add(1)
    obj.add(2)
    obj.add(3)
    obj.add(4)
    assert obj.read() == 10

def test_target():
    receiver = Box()
    assert receiver.read() == 0
''')
    candidates = for_target(corpus, generate_state_contexts(corpus))
    assert {row['provenance']['operation_count'] for row in candidates} == {1, 2, 3}
    assert any(row['arg_values'] == [1, 2, 3] for row in candidates)
    assert not any(row['arg_values'] == [1, 3] for row in candidates)
    assert all(row['provenance']['observation_state_witnesses'] for row in candidates)


@pytest.mark.parametrize('setup, operation', [
    ('amount = dynamic()', 'obj.add(amount)'),
    ('amount = [1]\n    mutate(amount)', 'obj.add(amount)'),
    ('', 'obj.add(missing)'),
    ('', 'obj.add(dynamic())'),
])
def test_missing_or_nonliteral_dependencies_are_rejected(tmp_path, setup, operation):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def dynamic(): return 3
def mutate(value): pass
def test_donor():
    obj = Box()
    ''' + setup + '\n    ' + operation + '''
    assert obj.read() == 0

def test_target():
    receiver = Box()
    assert receiver.read() == 0
''')
    result = generate_state_contexts(corpus)
    assert not for_target(corpus, result)
    assert result['skipped']


def test_different_resolved_constructor_identity_is_not_same_named_method(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''class Other:
    def __init__(self): self.value = 0
    def add(self, value): self.value += value
    def read(self): return self.value

def test_donor():
    obj = Box()
    obj.add(3)
    assert obj.read() == 3

def test_target():
    obj = Other()
    assert obj.read() == 0
''')
    assert not generate_state_contexts(corpus)['candidates']


def test_unresolved_operation_separates_transferable_sequences(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
    obj.add(1)
    obj.add(missing)
    obj.add(3)
    assert obj.read() == 4

def test_target():
    receiver = Box()
    assert receiver.read() == 0
''')
    candidates = for_target(corpus, generate_state_contexts(corpus))
    assert {tuple(candidate['arg_values']) for candidate in candidates} == {(1,), (3,)}


def test_unknown_constructor_is_not_resolved_by_spelling(tmp_path):
    corpus = corpus_for(tmp_path, '''def test_donor():
    obj = unresolved()
    obj.add(3)
    assert obj.read() == 3

def test_target():
    obj = unresolved()
    assert obj.read() == 0
''')
    assert not generate_state_contexts(corpus)['candidates']


@pytest.mark.parametrize('middle', ['    if enabled:\n        obj.add(3)\n',
                                    '    obj.add((lambda: 3)())\n'])
def test_control_blocks_and_nested_callbacks_are_not_flattened(tmp_path, middle):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
''' + middle + '''
    assert obj.read() == 3

def test_target():
    obj = Box()
    assert obj.read() == 0
''')
    result = generate_state_contexts(corpus)
    assert not result['candidates']
    assert result['skipped']['control_or_nested_scope_requires_region_analysis']


def test_tests_in_distinct_enclosing_scopes_do_not_exchange_captures(tmp_path):
    corpus = corpus_for(tmp_path, '''import { Box } from './box';
describe('nested', () => {
    test('donor', () => {
        const obj = new Box();
        obj.add(3);
        expect(obj.read()).toEqual(3);
    });
});
test('target', () => {
    const obj = new Box();
    expect(obj.read()).toEqual(0);
});
''', 'typescript')
    assert not generate_state_contexts(corpus)['candidates']


def test_resolved_free_function_receiver_slot_is_transferred(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def apply(value, amount): value.add(amount)
def test_donor():
    obj = Box()
    apply(obj, 3)
    assert obj.read() == 3

def test_target():
    receiver = Box()
    assert receiver.read() == 0
''')
    candidates = for_target(corpus, generate_state_contexts(corpus))
    assert len(candidates) == 1
    assert 'apply(receiver, 3)' in candidates[0]['edits'][0]['after']
    assert candidates[0]['arg_values'] == [3]


def test_resolved_free_observer_is_not_misclassified_as_new_constructor(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def observe(value): return value.read()
def test_donor():
    obj = Box()
    obj.add(3)
    actual = observe(obj)
    assert actual == 3

def test_target():
    receiver = Box()
    actual = observe(receiver)
    assert actual == 0
''')
    candidate = for_target(corpus, generate_state_contexts(corpus))[0]
    edited = changed_source(corpus, candidate).split('def test_target():', 1)[1]
    assert edited.index('receiver.add(3)') < edited.index('actual = observe(receiver)')


@pytest.mark.parametrize('before, after', [('    apply = 9\n', ''), ('', '    apply = 9\n')])
def test_recipient_local_cannot_capture_a_donor_global_callee(tmp_path, before, after):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def apply(value, amount): value.add(amount)
def test_donor():
    obj = Box()
    apply(obj, 3)
    assert obj.read() == 3

def test_target():
    receiver = Box()
''' + before + '''
    assert receiver.read() == 0
''' + after)
    result = generate_state_contexts(corpus)
    assert not for_target(corpus, result)
    assert result['skipped']['external_callee_shadowed_at_target']


def test_heap_assignment_is_an_operation_but_unrelated_calls_are_not(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def unrelated(): pass
def test_donor():
    obj = Box()
    unrelated()
    obj.value = 6
    assert obj.read() == 6

def test_target():
    receiver = Box()
    assert receiver.read() == 0
''')
    candidate = for_target(corpus, generate_state_contexts(corpus))[0]
    assert 'receiver.value = 6' in candidate['edits'][0]['after']
    assert 'unrelated' not in candidate['edits'][0]['after']


GO_SOURCE = '''package toy
import "testing"
type Box struct { value int }
func NewBox() *Box { return &Box{} }
func (b *Box) Add(amount int) { b.value += amount }
func (b *Box) Read() int { return b.value }
func TestDonor(t *testing.T) {
    obj := NewBox()
    amount := 3
    alias := obj
    alias.Add(amount)
    if obj.Read() != 3 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
    receiver := NewBox()
    actual := receiver.Read()
    if actual != 0 { t.Fatal("wrong") }
}
'''


@pytest.mark.parametrize('language, code, target, observation', [
    ('go', GO_SOURCE, 'TestTarget', 'actual := receiver.Read()'),
    ('typescript', '''import { Box } from './box';
test('donor', () => {
    const obj = new Box();
    const amount = 3;
    const alias = obj;
    alias.add(amount);
    expect(obj.read()).toEqual(3);
});
test('target', () => {
    const receiver = new Box();
    const actual = receiver.read();
    expect(actual).toEqual(0);
});
''', 'target', 'const actual = receiver.read();'),
])
def test_go_and_typescript_source_roundtrip_and_snapshot_position(tmp_path, language, code, target, observation):
    corpus = corpus_for(tmp_path, code, language)
    result = generate_state_contexts(corpus)
    candidates = for_target(corpus, result, target)
    assert len(candidates) == 1, result['skipped']
    candidate = candidates[0]
    edited = changed_source(corpus, candidate)
    assert not Source('toy', edited, language).root.has_error
    assert candidate['arg_values'] == [3]
    assert 'alias :=' not in candidate['edits'][0]['after']
    assert 'const alias' not in candidate['edits'][0]['after']
    position = candidate['edits'][0]['span']['start_byte']
    assert code.encode()[position:].decode().startswith(observation)
    assert not emit(corpus, [candidate])['unsupported']


def test_go_emitted_context_has_no_unused_alias_or_literal_binding(tmp_path):
    executable = shutil.which('go')
    if executable is None:
        pytest.skip('Go compiler unavailable')
    corpus = corpus_for(tmp_path, GO_SOURCE, 'go')
    candidate = for_target(corpus, generate_state_contexts(corpus), 'TestTarget')[0]
    emitted = emit(corpus, [candidate])
    assert not emitted['unsupported']
    for filename, code in emitted['files'].items():
        (tmp_path / filename).write_text(code)
    environment = dict(os.environ, GO111MODULE='off', GOPROXY='off', GOTOOLCHAIN='local',
                       GOCACHE=str(tmp_path / 'go-cache'))
    process = subprocess.run([executable, 'test', '-run', '^$'], cwd=tmp_path, env=environment,
                             capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr


def test_generation_is_deterministic_and_budgeted(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
    obj.add(1)
    obj.add(2)
    assert obj.read() == 3

def test_target():
    receiver = Box()
    assert receiver.read() == 0
''')
    result = generate_state_contexts(corpus, max_candidates=2)
    assert result == generate_state_contexts(corpus, max_candidates=2)
    assert len(result['candidates']) == 2
    assert result['skipped']['candidate_budget'] == 1
    assert result['attempts'] == 2
    assert result['budget_exhausted']
    with pytest.raises(ValueError):
        generate_state_contexts(corpus, top_k=0)


def search_corpus(tmp_path):
    return corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
    obj.add(1)
    obj.add(2)
    obj.add(3)
    obj.add(4)
    assert obj.read() == 10

def test_first():
    receiver = Box()
    assert receiver.read() == 0

def test_second():
    receiver = Box()
    assert receiver.read() == 0
''')


@pytest.mark.parametrize('stage', ['_render', '_witness'])
def test_attempt_budget_terminates_even_when_every_splice_is_rejected(tmp_path, monkeypatch, stage):
    corpus = search_corpus(tmp_path)
    calls = []

    def reject(*args):
        calls.append(args)
        raise state_contexts.Unsupported('invented_rejection')

    monkeypatch.setattr(state_contexts, stage, reject)
    result = generate_state_contexts(corpus, max_attempts=5)
    assert result['candidates'] == []
    assert len(calls) == result['attempts'] == 5
    assert result['budget_exhausted']
    assert result['skipped'] == {'invented_rejection': 5, 'attempt_budget': 1}
    assert result == generate_state_contexts(corpus, max_attempts=5)
    with pytest.raises(ValueError):
        generate_state_contexts(corpus, max_attempts=0)


def test_seed_recipients_receive_round_robin_attempts_before_one_group_fills_budget(tmp_path):
    corpus = search_corpus(tmp_path)
    for test in corpus['tests'].values():
        test['retrieval_rank'] = {'test_first': 1, 'test_second': 2}.get(test['name'])
    result = generate_state_contexts(corpus, top_k=2, max_candidates=2)
    recipients = [corpus['tests'][row['base_test_id']]['name'] for row in result['candidates']]
    assert recipients == ['test_first', 'test_second']
    assert result['attempts'] == 2
    assert result == generate_state_contexts(corpus, top_k=2, max_candidates=2)


def test_unchanged_source_files_are_parsed_once_per_generation(tmp_path, monkeypatch):
    (tmp_path / 'test_unrelated.py').write_text('def test_other():\n    assert unrelated() == 1\n')
    corpus = search_corpus(tmp_path)
    parsed = []
    source_type = state_contexts.Source

    def parse(path, *args, **kwargs):
        parsed.append(path)
        return source_type(path, *args, **kwargs)

    monkeypatch.setattr(state_contexts, 'Source', parse)
    result = generate_state_contexts(corpus, max_candidates=4)
    assert len(result['candidates']) == 4
    assert parsed.count('test_unrelated.py') == 1
    assert parsed.count('test_context.py') == 1 + result['attempts']


def test_seed_fairness_crosses_producer_groups(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''class Other(Box): pass
def test_donor_first():
    obj = Box()
    obj.add(1)
    obj.add(2)
    obj.add(3)
    assert obj.read() == 6

def test_donor_second():
    obj = Other()
    obj.add(4)
    assert obj.read() == 4

def test_first():
    obj = Box()
    assert obj.read() == 0

def test_second():
    obj = Other()
    assert obj.read() == 0
''')
    for test in corpus['tests'].values():
        test['retrieval_rank'] = {'test_first': 1, 'test_second': 2}.get(test['name'])
    result = generate_state_contexts(corpus, top_k=2, max_candidates=2)
    assert [corpus['tests'][row['base_test_id']]['name'] for row in result['candidates']] == [
        'test_first', 'test_second']
    assert result['attempts'] == 2


def test_exhausted_search_without_a_limit_reports_complete_enumeration(tmp_path):
    corpus = corpus_for(tmp_path, PYTHON_BOX + '''def test_donor():
    obj = Box()
    obj.add(1)
    assert obj.read() == 1

def test_target():
    receiver = Box()
    assert receiver.read() == 0
''')
    result = generate_state_contexts(corpus)
    assert result['attempts'] == 1
    assert not result['budget_exhausted']


def test_typescript_shorthand_static_object_expands_values_without_renaming_keys(tmp_path):
    corpus = corpus_for(tmp_path, '''import { Box } from './box';
it('donor', () => {
    const obj = new Box();
    const amount = 3;
    const options = {amount, nested: {amount}, enabled: true};
    obj.add(options);
    expect(obj.read()).toEqual(3);
});
it('target', () => {
    const receiver = new Box();
    expect(receiver.read()).toEqual(0);
});
''', 'typescript')
    result = generate_state_contexts(corpus)
    candidate = for_target(corpus, result, 'target')[0]
    assert candidate['arg_values'] == [{'amount': 3, 'nested': {'amount': 3}, 'enabled': True}]
    assert candidate['edits'][0]['after'].count('amount: gc_ctx_') == 2
    assert 'receiver.add(gc_ctx_' in candidate['edits'][0]['after']
    assert candidate['provenance']['observation_state_witnesses']
    assert not emit(corpus, [candidate])['unsupported']


@pytest.mark.parametrize('argument', ['{missing}', '{...other}', '{[unknown]: 3}', '{__proto__: {}}', '{"__proto__": {}}'])
def test_typescript_dynamic_or_prototype_object_entries_are_not_literal_inputs(tmp_path, argument):
    corpus = corpus_for(tmp_path, '''import { Box } from './box';
it('donor', () => {
    const obj = new Box();
    obj.add(''' + argument + ''');
    expect(obj.read()).toEqual(3);
});
it('target', () => {
    const receiver = new Box();
    expect(receiver.read()).toEqual(0);
});
''', 'typescript')
    result = generate_state_contexts(corpus)
    assert not for_target(corpus, result, 'target')


def test_typescript_literal_object_passed_to_assigned_call_is_no_longer_static(tmp_path):
    corpus = corpus_for(tmp_path, '''import { Box, mutate } from './box';
it('donor', () => {
    const obj = new Box();
    const amount = 3;
    const options = {amount};
    const saved = mutate(options);
    obj.add(options);
    expect(obj.read()).toEqual(3);
});
it('target', () => {
    const receiver = new Box();
    expect(receiver.read()).toEqual(0);
});
''', 'typescript')
    result = generate_state_contexts(corpus)
    assert not for_target(corpus, result, 'target')
    assert result['skipped']['missing_literal_dependency']
