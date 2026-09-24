"""Independent source-to-source toys for bounded observation port migration."""
import copy
import json
import shutil
import subprocess

import pytest

from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from experimental.semantic_transport import oracle
from experimental.semantic_transport import model
from experimental.semantic_transport.proposals import generate, materialize
from experimental import observation_projection
from experimental.observation_projection import Budget, generate_projections, materialize_projection


STATE = '''class Sequence:
    def __init__(self): self.values = []
    def put(self, value): self.values.append(value)
    def size(self): return len(self.values)
    def snapshot(self): return self.values[:]
def test_a():
    s = Sequence()
    s.put('a')
    assert s.size() == 1
def test_b():
    s = Sequence()
    s.put('b')
    assert s.size() == 1
def test_observer():
    probe = Sequence()
    assert probe.snapshot() == []
'''

WRAPPER = '''class Atom:
    def __init__(self, text): self.text = text
class Envelope:
    def __init__(self, item): self.item = item
def wrap(item): return Envelope(item)
def test_plain():
    assert Atom('\\0').text == '\\0'
def test_wrapper():
    assert wrap(Atom('a')).item.text == 'a'
'''


def corpus_for(tmp_path, code, language='python'):
    name = {'python': 'test_toy.py', 'go': 'toy_test.go', 'typescript': 'toy.test.ts'}[language]
    (tmp_path / name).write_text(code)
    return build_corpus(tmp_path, language)


def complete(candidate, expression):
    result = oracle.validate_completions({'completions': [{
        'candidate_id': candidate['id'], 'observe': 0,
        'expected': expression, 'guard': None,
    }]}, [candidate])
    assert not result['rejected'], result
    return result['accepted'][0]


def run_emitted(corpus, candidate, expression):
    proposal = materialize_projection(corpus, candidate, complete(candidate, expression))
    result = emit(corpus, [proposal])
    assert not result['unsupported'], result
    namespace = {}
    exec(result['files']['test_toy.py'], namespace)
    for row in result['controls'] + result['obligations']:
        namespace[row['test_name']]()
    return namespace, result


def state_projection(corpus):
    pending = generate(corpus)['candidates']
    projections = generate_projections(corpus, pending)
    candidate = next(c for c in projections['candidates']
                     if c['observations'][0]['text'] == 's.snapshot()'
                     and c['arg'] == ['a', 'b'])
    return pending, projections, candidate


def test_integrated_generator_presentation_and_completion_select_transplanted_hole(tmp_path):
    corpus = corpus_for(tmp_path, STATE)
    pending = generate(corpus)
    candidate = next(c for c in pending['candidates'] if c.get('projection')
                     and c['observations'][0]['text'] == 's.snapshot()' and c['arg'] == ['a', 'b'])
    pending = dict(pending, candidates=[candidate], shown_ids=[candidate['id']])
    shown = model.presentation(corpus, {'issue': 'Sequence.put appends a value.'}, pending)
    row = shown['candidates'][0]
    assert row['expected_hole']['source_expected_slot'] == 1
    assert row['expected_hole']['original_text'] == '[]'
    validation = model.resolve_completion(json.dumps({'completions': [{
        'candidate_id': 'c0', 'observe': 0, 'expected': 'list(arg)', 'guard': None,
    }]}), pending)
    assert not validation['rejected']
    proposal = materialize(corpus, candidate, validation['accepted'][0])
    result = emit(corpus, [proposal])
    assert not result['unsupported']
    namespace = {}
    exec(result['files']['test_toy.py'], namespace)
    for item in result['controls'] + result['obligations']:
        namespace[item['test_name']]()


def test_state_observer_exposes_order_defect_hidden_by_count(tmp_path):
    corpus = corpus_for(tmp_path, STATE)
    before = copy.deepcopy(corpus)
    pending, result, candidate = state_projection(corpus)
    original = next(c for c in pending if c['id'] == candidate['projection']['action_candidate_id'])
    assert candidate['pre'] == [1, []]
    assert candidate['projection']['source_expected_slot'] == 1
    assert candidate['preview_body'].count('.put(') == 2
    assert candidate['projection']['action_context_id'] == original['context']['id']
    namespace, emitted = run_emitted(corpus, candidate, 'list(arg)')
    namespace['Sequence'].put = lambda self, value: self.values.insert(0, value)
    for row in emitted['controls']:
        namespace[row['test_name']]()
    with pytest.raises(AssertionError):
        namespace[emitted['obligations'][0]['test_name']]()
    old = emit(corpus, [materialize(corpus, original, complete(original, 'pre[0] + 1'))])
    old_namespace = {}
    exec(old['files']['test_toy.py'], old_namespace)
    old_namespace['Sequence'].put = lambda self, value: self.values.insert(0, value)
    old_namespace[old['obligations'][0]['test_name']]()
    assert corpus == before


def test_type_changing_wrapper_observation_preserves_action_once(tmp_path):
    corpus = corpus_for(tmp_path, WRAPPER)
    pending = generate(corpus)['candidates']
    before = copy.deepcopy(pending)
    projections = generate_projections(corpus, pending)
    candidate = next(c for c in projections['candidates']
                     if c['pre'][0] == '\0' and '.item.text' in c['observations'][0]['text'])
    assert candidate['preview_body'].count('wrap(') == 1
    assert candidate['arg'] == ['\0']
    namespace, result = run_emitted(corpus, candidate, 'pre[0]')
    namespace['wrap'] = lambda item: namespace['Envelope'](namespace['Atom'](item.text.replace('\0', '')))
    for row in result['controls']:
        namespace[row['test_name']]()
    with pytest.raises(AssertionError):
        namespace[result['obligations'][0]['test_name']]()
    assert pending == before


def test_literal_observer_dependency_is_closed_without_free_local(tmp_path):
    code = STATE.replace('assert probe.snapshot() == []', "probe.put('x')\n    position = 0\n    assert probe.snapshot()[position] == 'x'")
    corpus = corpus_for(tmp_path, code)
    candidates = generate_projections(corpus, generate(corpus)['candidates'])['candidates']
    candidate = next(c for c in candidates if c['arg'] == ['a', 'b'] and 'snapshot()[0]' in c['observations'][0]['text'])
    assert 'position' not in candidate['preview_body']
    run_emitted(corpus, candidate, 'arg[0]')


def test_unrelated_types_and_missing_second_object_are_not_transplanted(tmp_path):
    code = STATE + '''class Unrelated:
    def snapshot(self): return ['foreign']
def test_foreign():
    foreign = Unrelated()
    assert foreign.snapshot() == ['foreign']
def test_two_roots():
    left = Sequence()
    right = Sequence()
    assert left.snapshot() + right.snapshot() == []
'''
    corpus = corpus_for(tmp_path, code)
    result = generate_projections(corpus, generate(corpus)['candidates'])
    candidates = [c for c in result['candidates'] if c['arg'] == ['a', 'b']]
    assert candidates
    assert all('foreign' not in c['projection']['source_root'] for c in candidates)
    assert all('right' not in c['observations'][0]['text'] and 'left' not in c['observations'][0]['text'] for c in candidates)
    assert result['skipped'].get('observer_object_binding_unavailable', 0)


def test_model_cannot_change_selected_body_inputs_or_forge_cached_literal(tmp_path):
    corpus = corpus_for(tmp_path, STATE)
    _, _, candidate = state_projection(corpus)
    accepted = complete(candidate, 'list(arg)')
    with pytest.raises(ValueError, match='completion_literal_mismatch'):
        materialize_projection(corpus, candidate, dict(accepted, literal="[]\n    raise RuntimeError()"))
    with pytest.raises(ValueError, match='completion_candidate_mismatch'):
        materialize_projection(corpus, candidate, dict(accepted, candidate_id='forged'))
    for field in ['body', 'arg', 'observations']:
        result = oracle.validate_completions({'completions': [{
            'candidate_id': candidate['id'], 'observe': 0, 'expected': 'list(arg)', 'guard': None,
            field: 'injected',
        }]}, [candidate])
        assert result['protocol_error']['code'] == 'completion_schema'


def test_projection_is_deterministic_and_bounded(tmp_path):
    corpus = corpus_for(tmp_path, STATE)
    pending = generate(corpus)['candidates']
    budget = Budget(max_candidates=2, projections_per_action=1)
    first = generate_projections(corpus, pending, budget)
    assert first == generate_projections(corpus, pending, budget)
    assert len(first['candidates']) == 2
    assert len({c['projection']['action_candidate_id'] for c in first['candidates']}) == 2


def test_typescript_migrates_assertion_predicate_with_observer(tmp_path):
    if not shutil.which('node'):
        pytest.skip('node unavailable')
    code = '''import assert from 'node:assert/strict';
import {test} from 'node:test';
class Sequence {
    constructor() { this.values = []; }
    put(value) { this.values.push(value); }
    size() { return this.values.length; }
    snapshot() { return this.values.slice(); }
}
test('a', () => { const s = new Sequence(); s.put('a'); assert.strictEqual(s.size(), 1); });
test('b', () => { const s = new Sequence(); s.put('b'); assert.strictEqual(s.size(), 1); });
test('observer', () => { const probe = new Sequence(); assert.deepEqual(probe.snapshot(), []); });
'''
    corpus = corpus_for(tmp_path, code, 'typescript')
    pending = generate(corpus)['candidates']
    projections = generate_projections(corpus, pending)
    candidate = next(c for c in projections['candidates'] if c['arg'] == ['a', 'b'] and '.snapshot()' in c['observations'][0]['text'])
    assert 'assert.deepEqual' in candidate['preview_body']
    proposal = materialize_projection(corpus, candidate, complete(candidate, 'list(arg)'))
    result = emit(corpus, [proposal])
    assert not result['unsupported'], result
    output = tmp_path / 'projected.mjs'
    output.write_text(result['files']['toy.test.ts'])
    executed = subprocess.run(['node', str(output)], capture_output=True, text=True)
    assert executed.returncode == 0, executed.stderr


def test_initial_sources_are_parsed_once_then_only_action_file_reparsed(tmp_path, monkeypatch):
    corpus = corpus_for(tmp_path, STATE)
    extra = tmp_path / 'test_helper.py'
    extra.write_text('def identity(x): return x\ndef test_identity():\n    assert identity(0) == 0\n')
    corpus = build_corpus(tmp_path, 'python')
    pending = generate(corpus)['candidates']
    original, calls = observation_projection.Source, []

    def recording_source(path, code, language):
        calls.append(path)
        return original(path, code, language)

    monkeypatch.setattr(observation_projection, 'Source', recording_source)
    generate_projections(corpus, pending)
    for path in corpus['sources']:
        edits = sum(corpus['tests'][c['base_test_id']]['span']['path'] == path for c in pending)
        assert calls.count(path) == 1 + edits


def test_template_budget_uses_parent_retrieval_rank(tmp_path):
    corpus = corpus_for(tmp_path, STATE)
    for record in corpus['tests'].values():
        record['retrieval_rank'] = 1 if record['name'] == 'test_observer' else 2
    pending = generate(corpus)['candidates']
    result = generate_projections(corpus, pending, Budget(max_templates=1))
    assert result['candidates']
    assert all(c['projection']['source_observation'] == 'probe.snapshot()' for c in result['candidates'])


@pytest.mark.skipif(shutil.which('go') is None, reason='Go unavailable')
def test_go_projection_maps_fixture_and_preserves_unicode_byte_hole(tmp_path):
    code = '''package toy
import "testing"
type Sequence struct { text string; count int }
func NewSequence() *Sequence { return &Sequence{} }
func (q *Sequence) Put(x string) { q.text += x; q.count++ }
func (q *Sequence) Size() int { return q.count }
func (q *Sequence) Text() string { return q.text }
func TestA(t *testing.T) {
 q := NewSequence()
 q.Put("猫")
 if q.Size() != 1 { t.Fatal("count") }
}
func TestB(t *testing.T) {
 q := NewSequence()
 q.Put("b")
 if q.Size() != 1 { t.Fatal("count") }
}
func TestObserver(check *testing.T) {
 probe := NewSequence()
 if probe.Text() != "" { check.Fatal("text") }
}
'''
    corpus = corpus_for(tmp_path, code, 'go')
    result = generate_projections(corpus, generate(corpus)['candidates'])
    candidate = next(c for c in result['candidates'] if c['arg'] == ['猫', 'b'] and '.Text()' in c['observations'][0]['text'])
    assert 'check.Fatal' not in candidate['preview_body']
    assert 't.Fatal' in candidate['preview_body']
    proposal = materialize_projection(corpus, candidate, complete(candidate, 'arg[0] + arg[1]'))
    result = emit(corpus, [proposal])
    assert not result['unsupported'], result
    output = tmp_path / 'toy_test.go'
    output.write_text(result['files']['toy_test.go'])
    executed = subprocess.run(['go', 'test', str(output)], capture_output=True, text=True, timeout=45)
    assert executed.returncode == 0, executed.stdout + executed.stderr

PAIR = '''class PairBox:
    def __init__(self):
        self.values = []
        self.peer = None
    def put(self, value): self.values.append(value)
    def size(self): return len(self.values)
    def snapshot(self): return self.values[:]
def test_target():
    left = PairBox()
    right = PairBox()
    left.peer = right
    left.put('a')
    right.put('a')
    assert left.size() == 1
def test_action():
    subject = PairBox()
    subject.put('b')
    assert subject.size() == 1
def test_relation():
    first = PairBox()
    second = PairBox()
    first.put('a')
    second.put('a')
    assert first.snapshot() == second.snapshot()
'''


def multi_candidates(corpus):
    pending = [c for c in generate(corpus)['candidates'] if not c.get('projection')]
    return generate_projections(corpus, pending, Budget(projections_per_action=12))


def test_go_blank_identifier_has_no_object_binding_but_retains_rhs_effects():
    from anchor_retrieval.index import Index
    from anchor_retrieval.syntax import Source, child, walk

    source = Source('blank_test.go', '''package toy
import "testing"
type Box struct { n int }
func NewBox() *Box { return &Box{} }
func (b *Box) Touch() *Box { b.n++; return b }
func (b *Box) Size() int { return b.n }
func TestBlank(t *testing.T) {
 left := NewBox(); _ = left
 right := NewBox(); _ = right
 _ = left.Touch()
 if left.Size() != 1 { t.Fatal("size") }
}
''', 'go')
    index = Index([source], '')
    unit = next(unit for unit in index.units.values() if unit.name == 'TestBlank')
    flow = index.flow(unit.id)
    assert '_' not in flow.env
    assert not any(node.get('variable') == '_' for node in flow.nodes)
    effect = next(call for call in flow.calls if flow.nodes[call.node]['text'] == 'left.Touch()')
    assert effect.node in flow.slice([flow.assertions[0].node])
    statement = next(node for node in walk(unit.body) if node.type == 'if_statement')
    observed = child(child(statement, 'condition'), 'left')
    roots = observation_projection._roots(index, unit, observed)
    ports = observation_projection._target_ports(index, unit, statement, roots, Budget())
    names = {source.text(node) for port in ports for node in port['nodes']}
    assert names == {'left', 'right'}


def pair_candidate(result, actual):
    return next(c for c in result['candidates'] if c['observations'][0]['text'] == (
                    'True if (' + actual + ') else False'
                    if c['observations'][0]['expected_source']['kind'] == 'asserted_relation_truth' else actual)
                and "left.put('b')" in c['preview_body'] and "right.put('a')" in c['preview_body'])


def test_multi_object_relation_detects_cross_object_effect_hidden_by_single_count(tmp_path):
    corpus = corpus_for(tmp_path, PAIR)
    result = multi_candidates(corpus)
    candidate = pair_candidate(result, 'left.snapshot() == right.snapshot()')
    ports = candidate['projection']['port_bindings']
    assert len(ports) == 2
    assert len({p['target'] for p in ports}) == 2
    assert candidate['pre'][-1] is True
    assert candidate['observations'][0]['expected_source']['kind'] == 'asserted_relation_truth'
    assert candidate['observations'][0]['predicate'] == '=='
    namespace, emitted = run_emitted(corpus, candidate, 'False')
    original = namespace['PairBox'].put
    def broken(self, value):
        original(self, value)
        if value == 'b' and self.peer is not None:
            original(self.peer, value)
    namespace['PairBox'].put = broken
    for row in emitted['controls']:
        namespace[row['test_name']]()
    with pytest.raises(AssertionError):
        namespace[emitted['obligations'][0]['test_name']]()


def test_alias_ports_coalesce_and_repeated_roots_remain_consistent(tmp_path):
    code = PAIR.replace('assert first.snapshot() == second.snapshot()',
                        "alias = first\n    assert (first.snapshot(), alias.snapshot(), second.snapshot(), first.snapshot()) == (['a'], ['a'], ['a'], ['a'])")
    corpus = corpus_for(tmp_path, code)
    candidate = pair_candidate(multi_candidates(corpus), '(left.snapshot(), left.snapshot(), right.snapshot(), left.snapshot())')
    assert len(candidate['projection']['port_bindings']) == 2
    port = next(p for p in candidate['projection']['port_bindings'] if p['target'] == 'left')
    assert port['source_names'] == ['alias', 'first']
    assert port['source_alias_proof'] == 'same_lexical_value'
    run_emitted(corpus, candidate, "(['a','b'], ['a','b'], ['a'], ['a','b'])")


def test_source_identity_relation_is_migrated_without_recorded_output(tmp_path):
    corpus = corpus_for(tmp_path, PAIR.replace('assert first.snapshot() == second.snapshot()', 'assert first is not second'))
    candidate = pair_candidate(multi_candidates(corpus), 'left is not right')
    run_emitted(corpus, candidate, 'True')
    assert candidate['projection']['alias_status'] == 'shared_value_preserved; distinct_values_not_proved_nonalias'


def test_multi_ports_respect_budget_and_never_alias_distinct_source_ports(tmp_path):
    corpus = corpus_for(tmp_path, PAIR)
    pending = [c for c in generate(corpus)['candidates'] if not c.get('projection')]
    one = generate_projections(corpus, pending, Budget(max_ports=1))
    assert one['skipped']['observer_port_budget']
    assert all(len(c['projection']['port_bindings']) == 1 for c in one['candidates'])
    full = generate_projections(corpus, pending, Budget(max_bindings_per_template=1))
    assert full == generate_projections(corpus, pending, Budget(max_bindings_per_template=1))
    assert all(len({p['target'] for p in c['projection']['port_bindings']}) == len(c['projection']['port_bindings']) for c in full['candidates'])


def test_rebinding_source_alias_creates_two_ports_instead_of_tautology(tmp_path):
    code = PAIR.replace('assert first.snapshot() == second.snapshot()',
                        'alias = first\n    first = PairBox()\n    assert first is not alias')
    corpus = corpus_for(tmp_path, code)
    candidate = pair_candidate(multi_candidates(corpus), 'left is not right')
    assert len(candidate['projection']['port_bindings']) == 2
    assert all(len(p['source_names']) == 1 for p in candidate['projection']['port_bindings'])
    run_emitted(corpus, candidate, 'True')


def test_target_aliases_cannot_satisfy_two_distinct_ports(tmp_path):
    code = PAIR.replace('right = PairBox()', 'right = left').replace('assert left.size() == 1', 'assert left.size() == 2')
    corpus = corpus_for(tmp_path, code)
    pending = [c for c in generate(corpus)['candidates'] if not c.get('projection')
               and corpus['tests'][c['base_test_id']]['name'] == 'test_target']
    assert pending
    result = generate_projections(corpus, pending, Budget(projections_per_action=12))
    assert all(len(c['projection']['port_bindings']) == 1 for c in result['candidates'])
    assert result['skipped']['observer_object_binding_unavailable']


def test_target_alias_is_resolved_at_assignment_before_later_rebinding(tmp_path):
    code = PAIR.replace('right = PairBox()', 'right = left\n    left = PairBox()')
    corpus = corpus_for(tmp_path, code)
    candidate = pair_candidate(multi_candidates(corpus), 'left.snapshot() == right.snapshot()')
    assert len(candidate['projection']['port_bindings']) == 2
    run_emitted(corpus, candidate, 'False')


def test_nondominating_second_target_is_not_assumed_available(tmp_path):
    code = PAIR.replace('right = PairBox()', 'if flag:\n        right = PairBox()')
    corpus = corpus_for(tmp_path, code)
    pending = [c for c in generate(corpus)['candidates'] if not c.get('projection')
               and corpus['tests'][c['base_test_id']]['name'] == 'test_target']
    result = generate_projections(corpus, pending, Budget(projections_per_action=12))
    assert all(len(c['projection']['port_bindings']) == 1 for c in result['candidates'])


def test_repeated_root_does_not_duplicate_inline_wrapper_action(tmp_path):
    code = WRAPPER + '''def test_double():
    root = Envelope(Atom('a'))
    assert (root.item.text, root.item.text) == ('a', 'a')
'''
    corpus = corpus_for(tmp_path, code)
    pending = [c for c in generate(corpus)['candidates'] if not c.get('projection')
               and "wrap(Atom('\\0'))" in c['preview_body']]
    assert pending
    result = generate_projections(corpus, pending, Budget(projections_per_action=12))
    assert result['skipped']['would_duplicate_effectful_root']
    assert all(c['preview_body'].count('wrap(') == 1 for c in result['candidates'])


def test_builtin_container_roots_support_existing_value_relation(tmp_path):
    code = '''def consume(value): return value
def decorate(value): return '<' + value + '>'
def test_target():
    left = [consume('a')]
    right = [consume('a')]
    consume(left[0])
    assert len(left) == 1
def test_action():
    donor = [decorate(consume('b'))]
    consume(donor[0])
    assert len(donor) == 1
def test_relation():
    first = ['a']
    second = ['a']
    assert first[0] == second[0]
'''
    corpus = corpus_for(tmp_path, code)
    result = multi_candidates(corpus)
    candidates = [c for c in result['candidates'] if c['observations'][0]['text'] == 'True if (left[0] == right[0]) else False']
    assert candidates, result
    for candidate in candidates:
        assert all('@python:list' in p['types'] for p in candidate['projection']['port_bindings'])
        body = candidate['preview_body']
        expected = 'False' if "left = [decorate(consume('a'))]" in body and "right = [consume('a')]" in body else 'True'
        run_emitted(corpus, candidate, expected)


@pytest.mark.skipif(shutil.which('node') is None, reason='Node unavailable')
def test_typescript_existing_boolean_relation_migrates_both_objects(tmp_path):
    code = '''import assert from 'node:assert/strict';
import {test} from 'node:test';
class Box {
 constructor() { this.data = ''; }
 put(x) { this.data += x; }
 size() { return this.data.length; }
 text() { return this.data; }
}
test('target', () => { const left = new Box(); const right = new Box(); left.put('a'); right.put('a'); assert.strictEqual(left.size(), 1); });
test('action', () => { const q = new Box(); q.put('b'); assert.strictEqual(q.size(), 1); });
test('relation', () => { const first = new Box(); const second = new Box(); first.put('a'); second.put('a'); assert.strictEqual(first.text() === second.text(), true); });
'''
    corpus = corpus_for(tmp_path, code, 'typescript')
    candidate = next(c for c in multi_candidates(corpus)['candidates']
                     if c['observations'][0]['text'] == 'left.text() === right.text()'
                     and "left.put('b')" in c['preview_body'])
    result = emit(corpus, [materialize_projection(corpus, candidate, complete(candidate, 'False'))])
    assert not result['unsupported'], result
    output = tmp_path / 'projected.mjs'
    output.write_text(result['files']['toy.test.ts'])
    executed = subprocess.run(['node', str(output)], capture_output=True, text=True, timeout=20)
    assert executed.returncode == 0, executed.stdout + executed.stderr


@pytest.mark.skipif(shutil.which('go') is None, reason='Go unavailable')
def test_go_existing_boolean_relation_migrates_both_objects(tmp_path):
    code = '''package toy
import "testing"
type Box struct { text string }
func NewBox() *Box { return &Box{} }
func (q *Box) Put(x string) { q.text += x }
func (q *Box) Size() int { return len(q.text) }
func (q *Box) Text() string { return q.text }
func TestTarget(t *testing.T) {
 left := NewBox()
 right := NewBox()
 left.Put("猫")
 right.Put("猫")
 if left.Size() != 3 { t.Fatal("size") }
}
func TestAction(t *testing.T) {
 q := NewBox()
 q.Put("b")
 if q.Size() != 1 { t.Fatal("size") }
}
func TestRelation(check *testing.T) {
 first := NewBox()
 second := NewBox()
 first.Put("猫")
 second.Put("猫")
 if (first.Text() == second.Text()) != true { check.Fatal("relation") }
}
'''
    corpus = corpus_for(tmp_path, code, 'go')
    candidate = next(c for c in multi_candidates(corpus)['candidates']
                     if c['observations'][0]['text'] == '(left.Text() == right.Text())'
                     and 'left.Put("b")' in c['preview_body'])
    result = emit(corpus, [materialize_projection(corpus, candidate, complete(candidate, 'False'))])
    assert not result['unsupported'], result
    output = tmp_path / 'toy_test.go'
    output.write_text(result['files']['toy_test.go'])
    executed = subprocess.run(['go', 'test', str(output)], capture_output=True, text=True, timeout=45)
    assert executed.returncode == 0, executed.stdout + executed.stderr


def test_source_interobject_dependency_must_survive_binding(tmp_path):
    code = PAIR.replace('assert first.snapshot() == second.snapshot()',
                        'first.peer = second\n    assert first.snapshot() == second.snapshot()')
    corpus = corpus_for(tmp_path, code)
    result = multi_candidates(corpus)
    candidate = pair_candidate(result, 'left.snapshot() == right.snapshot()')
    assert candidate['projection']['required_port_dependencies'] == [[0, 1]]
    assert not any(c['observations'][0]['text'] == 'True if (right.snapshot() == left.snapshot()) else False'
                   and "left.put('b')" in c['preview_body'] for c in result['candidates'])
    run_emitted(corpus, candidate, 'False')
    code = code.replace('    left.peer = right\n', '')
    corpus = corpus_for(tmp_path, code)
    pending = [c for c in generate(corpus)['candidates'] if not c.get('projection')
               and corpus['tests'][c['base_test_id']]['name'] == 'test_target']
    assert pending
    result = generate_projections(corpus, pending)
    assert not any(len(c['projection']['port_bindings']) == 2 for c in result['candidates'])


def test_go_struct_copy_is_not_proven_reference_alias(tmp_path):
    code = '''package toy
import "testing"
type Box struct { x int }
func NewBox() Box { return Box{} }
func (q Box) Value() int { return q.x }
func TestRelation(t *testing.T) {
 first := NewBox()
 alias := first
 if (first.Value() == alias.Value()) != true { t.Fatal("relation") }
}
'''
    corpus = corpus_for(tmp_path, code, 'go')
    from collections import Counter
    templates = observation_projection._bank(corpus, observation_projection._index(corpus), Budget(), Counter())
    assert len(templates) == 1
    assert len(templates[0]['roots']) == 2
    assert all(len(root['nodes']) == 1 for root in templates[0]['roots'])


def test_projection_discards_witnesses_of_previous_observation(tmp_path):
    corpus = corpus_for(tmp_path, PAIR)
    pending = [c for c in generate(corpus)['candidates'] if not c.get('projection')]
    for candidate in pending:
        candidate['witnesses'] = [{'pre': [1], 'arg': ['b'], 'expected': 2}]
    result = generate_projections(corpus, pending)
    assert result['candidates']
    assert all('witnesses' not in candidate for candidate in result['candidates'])
    assert all('witnesses' in candidate for candidate in pending)


@pytest.mark.parametrize('operator,left_truth,expected,visited', [
    ('or', True, True, [('a', 'b')]),
    ('or', False, True, [('a', 'b'), ('a',)]),
    ('and', True, True, [('a', 'b'), ('a',)]),
    ('and', False, False, [('a', 'b')]),
])
def test_truth_relation_preserves_single_evaluation_and_short_circuit(tmp_path, operator, left_truth, expected, visited):
    truth = 'True' if left_truth else 'len(self.values) < 2'
    code = 'events = []\n' + PAIR.replace(
        '    def size(self):',
        '    def probe(self):\n        events.append(("probe", tuple(self.values)))\n        return self\n'
        '    def __bool__(self):\n        events.append(("truth", tuple(self.values)))\n        return ' + truth + '\n'
        '    def size(self):')
    code = code.replace('    left = PairBox()', '    bool = 0\n    left = PairBox()')
    code = code.replace('assert first.snapshot() == second.snapshot()',
                        'assert first.probe() ' + operator + ' second.probe()')
    corpus = corpus_for(tmp_path, code)
    candidate = pair_candidate(multi_candidates(corpus), 'left.probe() ' + operator + ' right.probe()')
    actual = 'True if (left.probe() ' + operator + ' right.probe()) else False'
    assert candidate['observations'][0]['text'] == actual
    assert 'bool(' not in candidate['preview_body']
    namespace, emitted = run_emitted(corpus, candidate, repr(expected))
    namespace['events'].clear()
    namespace[emitted['obligations'][0]['test_name']]()
    assert namespace['events'] == [(kind, value) for value in visited for kind in ('probe', 'truth')]


def test_comparison_truth_does_not_compare_its_returned_object_with_true(tmp_path):
    code = '''events = []
class Verdict:
    def __bool__(self):
        events.append('truth')
        return True
    def __eq__(self, other):
        raise AssertionError('A truth value must not be compared with True')
''' + PAIR.replace('    def size(self):',
                   "    def __eq__(self, other):\n        events.append('compare')\n        return Verdict()\n    def size(self):")
    code = code.replace('assert first.snapshot() == second.snapshot()', 'assert first == second')
    corpus = corpus_for(tmp_path, code)
    candidate = pair_candidate(multi_candidates(corpus), 'left == right')
    namespace, emitted = run_emitted(corpus, candidate, 'True')
    namespace['events'].clear()
    namespace[emitted['obligations'][0]['test_name']]()
    assert namespace['events'] == ['compare', 'truth']
