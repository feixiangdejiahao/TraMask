"""Independent source-to-source toys for single-root observation migration."""
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


def test_unrelated_types_and_unclosed_second_object_are_not_transplanted(tmp_path):
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
    assert result['skipped'].get('observer_local_dependency_not_literal', 0)


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
