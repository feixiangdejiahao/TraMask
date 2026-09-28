"""Independent stateful subjects; generation never executes these programs."""
import ast
import json

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.state_cells import StateBudget, generate_state_cells


SUBJECT = '''events = []
class Ledger:
    def __init__(self): self.entries = {}
    def record(self, payload):
        events.append(('record', payload))
        self.entries.update(payload)
        return len(self.entries)
    def discard(self, key):
        events.append(('discard', key))
        self.entries.pop(key, None)
    def valid(self):
        events.append(('observe', None))
        return all(isinstance(v, list) for v in self.entries.values())

'''


def corpus_for(code, language='python'):
    path = {'python': 'test_states.py', 'typescript': 'states.test.ts', 'go': 'states_test.go'}[language]
    return to_emitter_corpus(extract_frontend([Source(path, code, language)]))


def named(corpus, name):
    return next(row['id'] for row in corpus['tests'].values() if row['name'] == name)


def run_candidate(corpus, candidate):
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    namespace = {}
    for code in output['files'].values():
        exec(compile(code, '<state-witness>', 'exec'), namespace)
    namespace[output['obligations'][0]['test_name']]()
    return namespace, output


def test_two_source_actions_compose_on_existing_receiver_with_complex_literal_closure():
    corpus = corpus_for(SUBJECT + '''def test_store():
    source = Ledger()
    payload = {'alpha': [1, 2], 'beta': [{'flag': True}]}
    alias = source
    saved = alias.record(payload)
    assert source.valid() is True

def test_remove():
    other = Ledger()
    other.discard('alpha')
    assert other.valid() is True

def test_target():
    receiver = Ledger()
    assert receiver.valid() is True
''')
    result = generate_state_cells(corpus)
    store, remove, target = (named(corpus, name) for name in ('test_store', 'test_remove', 'test_target'))
    candidate = next(row for row in result['candidates'] if row['base_test_id'] == target
                     and [a['source_test_id'] for a in row['provenance']['actions']] == [store, remove])
    assert candidate['relation']['cell']['operation_count'] == 2
    assert candidate['source_test_ids'] == sorted([store, remove])
    text = candidate['edits'][0]['after']
    assert 'receiver.record(gc_ctx_' in text and "receiver.discard('alpha')" in text
    assert 'saved =' not in text and 'payload =' not in text and 'Ledger()' not in text
    first, second = candidate['provenance']['actions']
    assert first['receiver_mapping'] == {'alias': 'receiver'}
    assert first['discarded_result_binding'] == 'saved'
    assert first['expression_span'] and first['literal_binding_renames']['payload']
    assert second['receiver_mapping'] == {'other': 'receiver'}
    namespace, _ = run_candidate(corpus, candidate)
    assert namespace['events'] == [('record', {'alpha': [1, 2], 'beta': [{'flag': True}]}),
                                   ('discard', 'alpha'), ('observe', None)]
    assert candidate['oracle']['applicability'] == 'requires_independent_admission'


def test_no_current_program_state_edge_is_required(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('current-program may-state evidence must not gate source construction')
    monkeypatch.setattr('experimental.semantic_transport.state_contexts._witness', forbidden)
    corpus = corpus_for('''class Marker:
    def touch(self, value): pass
    def ready(self): return True

def test_actions():
    obj = Marker()
    obj.touch({'nested': [1, {'two': 2}]})
    assert obj.ready() is True

def test_observer():
    obj = Marker()
    assert obj.ready() is True
''')
    target = named(corpus, 'test_observer')
    candidates = [row for row in generate_state_cells(corpus)['candidates'] if row['base_test_id'] == target]
    assert candidates
    for candidate in candidates:
        assert candidate['relation']['state_effect_status'] == 'unknown_not_required_for_materialization'
        assert candidate['provenance']['observation_state_witnesses'] == []
        run_candidate(corpus, candidate)


def test_compact_snapshot_alias_is_observed_before_later_mutation_and_rebinding():
    corpus = corpus_for(SUBJECT + '''def test_donor():
    obj = Ledger()
    obj.discard('alpha')
    assert obj.valid() is True

def test_snapshot():
    receiver = Ledger()
    actual = receiver.valid()
    copied = actual
    receiver.record({'after': [3]})
    actual = False
    assert copied is True
''')
    target = named(corpus, 'test_snapshot')
    candidates = [row for row in generate_state_cells(corpus)['candidates'] if row['base_test_id'] == target]
    assert candidates
    candidate = next(row for row in candidates if row['provenance']['operation_count'] == 1)
    code = corpus['sources']['test_states.py']['code']
    assert candidate['edits'][0]['span']['start_byte'] == code.index('actual = receiver.valid()')
    namespace, _ = run_candidate(corpus, candidate)
    assert namespace['events'] == [('discard', 'alpha'), ('observe', None), ('record', {'after': [3]})]
    assert all('record' not in row['edits'][0]['after'] for row in candidates)


def test_candidates_are_balanced_by_parent_then_observation_and_sequence_length():
    code = SUBJECT + ''.join(f'''def test_{name}():
    obj = Ledger()
    obj.discard('{name}')
    assert obj.valid() is True

''' for name in ('north', 'south', 'east'))
    corpus = corpus_for(code)
    for rank, row in enumerate(reversed(list(corpus['tests'].values())), 1):
        row['retrieval_rank'] = rank
    budget = StateBudget(max_candidates=6)
    result = generate_state_cells(corpus, budget=budget)
    assert len(result['candidates']) == 6
    assert len({row['base_test_id'] for row in result['candidates'][:3]}) == 3
    assert {row['provenance']['operation_count'] for row in result['candidates']} == {1, 2}
    assert [row['selection']['base_retrieval_rank'] for row in result['candidates'][:3]] == [1, 2, 3]
    assert result['budget_exhausted']
    assert result == generate_state_cells(corpus, budget=budget)
    json.dumps(result)


def test_context_manager_scope_and_local_constructor_identity_are_preserved():
    corpus = corpus_for('''from contextlib import contextmanager
events = []
@contextmanager
def scope():
    events.append('enter')
    try: yield
    finally: events.append('exit')

def test_regions():
    class Local:
        def touch(self, payload): events.append(payload)
        def ready(self): return True
    with scope():
        first = Local()
        first.touch({'value': [5]})
        assert first.ready() is True
    with scope():
        second = Local()
        actual = second.ready()
        assert actual is True
''')
    result = generate_state_cells(corpus)
    candidate = next(row for row in result['candidates'] if row['provenance']['recipient_receiver'] == 'second'
                     and row['provenance']['operation_count'] == 1)
    assert candidate['provenance']['producer_identity'][0] == 'lexical_declaration'
    assert candidate['provenance']['recipient_region']['context']
    assert 'class Local' not in candidate['edits'][0]['after']
    namespace, output = run_candidate(corpus, candidate)
    assert namespace['events'] == ['enter', {'value': [5]}, 'exit', 'enter', {'value': [5]}, 'exit']
    ast.parse(next(iter(output['files'].values())))


def test_different_local_declarations_and_unclosed_dependencies_are_not_merged():
    corpus = corpus_for('''def test_one():
    class Local:
        def touch(self, value): pass
        def ready(self): return True
    receiver = Local()
    receiver.touch(1)
    receiver.touch(unknown_name)
    assert receiver.ready() is True

def test_two():
    class Local:
        def touch(self, value): pass
        def ready(self): return True
    receiver = Local()
    assert receiver.ready() is True
''')
    result = generate_state_cells(corpus)
    assert result['candidates']
    assert result['skipped']['missing_literal_dependency']
    for candidate in result['candidates']:
        assert candidate['source_test_ids'] == [candidate['base_test_id']]
        assert 'unknown_name' not in candidate['edits'][0]['after']


@pytest.mark.parametrize('budget', [StateBudget(max_candidates=0), StateBudget(max_steps=3), StateBudget(top_k=0)])
def test_invalid_bounds_are_rejected(budget):
    with pytest.raises(ValueError, match='State budgets'):
        generate_state_cells(corpus_for('def test_one(): assert True'), budget=budget)


def test_attempt_bound_counts_lexically_rejected_transfers():
    corpus = corpus_for('''class Box:
    def ready(self): return True
def wrap(obj): pass

def test_donor():
    obj = Box()
    wrap(obj)
    assert obj.ready() is True

def test_target():
    obj = Box()
    wrap = 0
    assert obj.ready() is True
''')
    target = corpus['tests'][named(corpus, 'test_target')]
    target['retrieval_rank'] = 1
    result = generate_state_cells(corpus, budget=StateBudget(max_attempts=1))
    assert result['attempts'] == 1 and result['budget_exhausted']
    assert result['candidates'] == []
    assert result['skipped']['external_callee_shadowed_at_target'] == 1


@pytest.mark.parametrize(('language', 'code'), [
    ('typescript', '''class Container {
  add(record: object) {}
  ready() { return true; }
}
test('donor', () => {
  const obj = new Container();
  obj.add({alpha: [1, 2], nested: {flag: true}});
  expect(obj.ready()).toBe(true);
});
test('target', () => {
  const obj = new Container();
  expect(obj.ready()).toBe(true);
});
'''),
    ('go', '''package sample
import "testing"
type Container struct {}
func newContainer() *Container { return &Container{} }
func (c *Container) Add(value int) {}
func (c *Container) Ready() bool { return true }
func TestDonor(t *testing.T) {
    obj := newContainer()
    obj.Add(3)
    if !obj.Ready() { t.Fatal("not ready") }
}
func TestTarget(t *testing.T) {
    obj := newContainer()
    if !obj.Ready() { t.Fatal("not ready") }
}
'''),
])
def test_language_renderers_preserve_original_test_registration(language, code):
    corpus = corpus_for(code, language)
    result = generate_state_cells(corpus)
    assert result['candidates'], result['skipped']
    output = emit(corpus, result['candidates'][:2])
    assert not output['unsupported']
    for path, code in output['files'].items():
        assert not Source(path, code, language).root.has_error


def test_argument_metadata_round_trips_bytes_tuples_and_ordered_mapping_keys():
    from experimental.semantic_transport.oracle import decode_value

    corpus = corpus_for('''events = []
class Holder:
    def push(self, value): events.append(value)
    def ready(self): return True

def test_donor():
    obj = Holder()
    payload = (b'\\x00\\xff', {('nested', 1): (b'ab', [3, 4])})
    obj.push(payload)
    assert obj.ready() is True

def test_target():
    obj = Holder()
    assert obj.ready() is True
''')
    result = generate_state_cells(corpus)
    wire = json.loads(json.dumps(result, sort_keys=True))
    target = named(corpus, 'test_target')
    candidate = next(row for row in wire['candidates'] if row['base_test_id'] == target
                     and row['provenance']['operation_count'] == 1)
    expected = (b'\x00\xff', {('nested', 1): (b'ab', [3, 4])})
    assert decode_value(candidate['arg_values'][0]) == expected
    assert '$tuple' in candidate['arg_values'][0]
    namespace, _ = run_candidate(corpus, candidate)
    assert namespace['events'] == [expected]
