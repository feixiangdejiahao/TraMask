"""Two program-generated source witnesses compose without oracle synthesis."""
import copy
import json
import os
import shutil
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.atomic_observations import atomize_candidates
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.producer_contexts import generate_producer_contexts
from relational_gap.scalar_cells import generate_scalar_cells
from relational_gap.witness_composition import CompositionBudget, compose_witnesses


CODE = '''events = []
class Child:
    def __init__(self): self.value = 0
    def add(self, value): self.value += value; events.append(('add', value))
    def position(self): events.append(('position', self.value)); return self.value
class Device:
    def __init__(self): self.current = 0; events.append(('create', 0))
    def begin(self): events.append(('begin', 0)); return Child()
    def apply(self, child): self.current = child.value; events.append(('apply', child.value))
    def wait(self, position: int): events.append(('wait', position)); return position > self.current

def test_donor():
    amount = 2
    obj = Device()
    child = obj.begin()
    child.add(amount)
    obj.apply(child)
    x = child.position()
    assert not obj.wait(x)

def test_recipient():
    receiver = Device()
    handle = receiver.wait(1000)
    assert handle is True
'''


def prepare(code=CODE, language='python'):
    path = 'test_composition.py' if language == 'python' else 'composition_test.go'
    facts = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(facts)
    producers = generate_producer_contexts(corpus, facts)['candidates']
    scalars = generate_scalar_cells(corpus, facts)['candidates']
    return corpus, facts, producers, scalars


def matching_scalar(producer, scalars):
    return next(s for s in scalars if s['base_test_id'] == producer['base_test_id']
                and s['edits'][0]['span'] == producer['provenance']['recipient_argument_span'])


def test_composition_retains_prefix_q_and_parents_without_mutating_inputs():
    corpus, facts, producers, scalars = prepare()
    original = copy.deepcopy(producers + scalars)
    result = compose_witnesses(corpus, facts, producers + scalars)
    assert len(result['candidates']) == 2 and not result['skipped']
    assert producers + scalars == original
    assert result == compose_witnesses(corpus, facts, producers + scalars)
    producer, = producers
    original_argument = next(e for e in producer['edits'] if e['role'] == 'source_produced_argument')
    for row in result['candidates']:
        assert row['source_observation_id'] == producer['source_observation_id']
        assert row['oracle'] == producer['oracle']
        assert row['imports'] == producer['imports']
        assert row['edits'][0] == producer['edits'][0]
        argument = next(e for e in row['edits'] if e['role'] == 'source_produced_argument')
        assert argument['span'] == original_argument['span']
        assert argument['before'] == original_argument['before']
        assert argument['after'].count(original_argument['after']) == 1
        assert argument['after'] in {'(' + original_argument['after'] + ') - 1', '(' + original_argument['after'] + ') + 1'}
        assert row['parent_candidate_ids'][0] == producer['id']
        assert row['parent_candidate_ids'][1] in {s['id'] for s in scalars}
        assert row['relation']['numeric_type']['kind'] == 'integer'
        assert row['relation']['status'] == 'hypothesis_runtime_relation_unconfirmed'
    json.dumps(result)


def test_identical_edits_keep_all_source_constraints_for_composition():
    code = CODE.replace(
        "    def wait(self, position: int): events.append(('wait', position)); return position > self.current",
        "    def wait(self, position: int):\n"
        "        if position == 0: return False\n"
        "        return position > self.current").replace('receiver.wait(1000)', 'receiver.wait(0)')
    corpus, facts, producers, scalars = prepare(code)
    producer, = producers
    selected = matching_scalar(producer, scalars)
    assert selected['relation']['construction'] == 'exact_affine_boundary'
    assert any(r['construction'] == 'unknown_boundary_neighbor'
               for r in selected['source_constraint_derivations'])
    signatures = [json.dumps(c['edits'], sort_keys=True) for c in scalars]
    assert len(signatures) == len(set(signatures))
    combined = compose_witnesses(corpus, facts, producers + scalars)
    assert len(combined['candidates']) == 2
    for candidate in combined['candidates']:
        assert candidate['relation']['scalar_relation']['construction'] == 'unknown_boundary_neighbor'
        assert candidate['provenance']['composition']['scalar_derivation'] == candidate['relation']['scalar_relation']


def test_original_controls_and_positive_neighbour_pass_and_negative_remains_unconfirmed():
    corpus, facts, producers, scalars = prepare()
    result = compose_witnesses(corpus, facts, producers + scalars)
    atomic = atomize_candidates(corpus, facts, result['candidates'])
    assert not atomic['unknowns']
    for row in atomic['candidates']:
        output = emit(corpus, [row])
        assert not output['unsupported']
        namespace = {}
        exec(output['files']['test_composition.py'], namespace)
        for control in output['controls']:
            namespace['events'].clear()
            namespace[control['test_name']]()
        namespace['events'].clear()
        witness = namespace[output['obligations'][0]['test_name']]
        if row['relation']['offset'] == 1:
            witness()
        else:
            with pytest.raises(AssertionError):
                witness()
        assert namespace['events'] == [('create', 0), ('begin', 0), ('add', 2), ('apply', 2),
                                        ('position', 2), ('wait', 2 + row['relation']['offset'])]


@pytest.mark.parametrize('kind', ['source_integer_expression', 'unknown', 'non_integer', None])
def test_original_literal_integer_is_not_a_formal_type_proof(kind):
    corpus, facts, producers, scalars = prepare()
    scalar = copy.deepcopy(matching_scalar(producers[0], scalars))
    scalar['relation']['numeric_type'] = {} if kind is None else {'kind': kind}
    result = compose_witnesses(corpus, facts, [*producers, scalar])
    assert not result['candidates']
    assert result['skipped']['composition_source_formal_integer_evidence_missing']


@pytest.mark.parametrize('construction', ['exact_affine_boundary', 'observed_mask_set', 'observed_mask_clear'])
def test_other_scalar_cells_are_not_blindly_rebased_on_produced_value(construction):
    corpus, facts, producers, scalars = prepare()
    scalar = copy.deepcopy(matching_scalar(producers[0], scalars))
    scalar['relation']['construction'] = construction
    assert not compose_witnesses(corpus, facts, [*producers, scalar])['candidates']


@pytest.mark.parametrize('offset', [0, 2, -2, True, 1.0])
def test_offset_is_exact_integer_unit_neighbour(offset):
    corpus, facts, producers, scalars = prepare()
    scalar = copy.deepcopy(matching_scalar(producers[0], scalars))
    scalar['relation']['cell']['offset'] = offset
    result = compose_witnesses(corpus, facts, [*producers, scalar])
    assert not result['candidates']
    assert result['skipped']['composition_offset_not_unit_neighbor']


@pytest.mark.parametrize('role', ['semantic_expected', 'atomic_neutralization', 'source_normal_result_guard'])
def test_oracle_and_neutralization_edits_are_never_composed(role):
    corpus, facts, producers, scalars = prepare()
    producer = copy.deepcopy(producers[0])
    q = next(q for q in corpus['capsules'] if q['id'] == producer['source_observation_id'])
    producer['edits'].append({'span': q['expected']['span'], 'before': 'True', 'after': 'False', 'role': role})
    result = compose_witnesses(corpus, facts, [producer, *scalars])
    assert not result['candidates']
    assert result['skipped']['composition_oracle_neutralization_or_other_edit']


def test_atomic_parent_is_rejected_even_if_its_input_edits_happen_to_match():
    corpus, facts, producers, scalars = prepare()
    atomic = atomize_candidates(corpus, facts, producers)
    result = compose_witnesses(corpus, facts, [*atomic['candidates'], *scalars])
    assert not result['candidates']
    assert result['skipped']['composition_requires_pre_atomic_parent']


def test_different_base_or_actual_span_has_no_composition():
    code = CODE + '''
def test_another():
    other = Device()
    flag = other.wait(999)
    assert flag is True
'''
    corpus, facts, producers, scalars = prepare(code)
    producer = next(p for p in producers if p['base_test_id'].endswith(':test_recipient'))
    other_scalars = [s for s in scalars if s['base_test_id'].endswith(':test_another')]
    assert not compose_witnesses(corpus, facts, [producer, *other_scalars])['candidates']
    forged = copy.deepcopy(matching_scalar(producer, scalars))
    forged['relation']['argument_slot'] += 1
    result = compose_witnesses(corpus, facts, [producer, forged])
    assert not result['candidates']
    assert result['skipped']['composition_actual_call_or_slot_mismatch']


def test_budgets_are_fair_across_recipient_tests_and_duplicate_parent_cells_collapse():
    code = CODE + '''
def test_another():
    other = Device()
    flag = other.wait(999)
    assert flag is True
'''
    corpus, facts, producers, scalars = prepare(code)
    result = compose_witnesses(corpus, facts, producers + scalars, budget=CompositionBudget(max_candidates=2))
    assert len(result['candidates']) == 2
    assert len({row['base_test_id'] for row in result['candidates']}) == 2
    assert result['budget_exhausted']
    copies = copy.deepcopy(scalars)
    for row in copies:
        row['id'] += '_duplicate'
    result = compose_witnesses(corpus, facts, producers + scalars + copies)
    assert len(result['candidates']) == 4
    assert result['skipped']['composition_duplicate'] == 4
    limited = compose_witnesses(corpus, facts, producers + scalars, budget=CompositionBudget(max_attempts=1))
    assert len(limited['candidates']) == limited['attempts'] == 1
    assert limited['budget_exhausted']


@pytest.mark.parametrize('kwargs', [{'max_candidates': 0}, {'max_attempts': 0}, {'max_attempts': True}])
def test_invalid_budgets(kwargs):
    with pytest.raises(ValueError):
        CompositionBudget(**kwargs)


def test_source_mismatch_and_missing_parent_metadata_are_explicit_unknowns():
    corpus, facts, producers, scalars = prepare()
    producer = copy.deepcopy(producers[0])
    producer['edits'][1]['before'] = 'not the source'
    assert not compose_witnesses(corpus, facts, [producer, *scalars])['candidates']
    scalar = copy.deepcopy(matching_scalar(producers[0], scalars))
    del scalar['relation']['call_span']
    result = compose_witnesses(corpus, facts, [*producers, scalar])
    assert not result['candidates']
    assert result['skipped']['composition_parent_metadata_invalid']


def test_go_integer_alias_neighbour_compiles_and_keeps_one_source_value_production(tmp_path):
    code = '''package sample
import "testing"
type Position uint64
type Child struct { value Position }
func (c *Child) Add(n Position) { c.value += n }
func (c *Child) Position() Position { return c.value }
type Device struct { current Position }
func Make() *Device { return &Device{} }
func (d *Device) Begin() *Child { return &Child{} }
func (d *Device) Apply(c *Child) { d.current = c.value }
func (d *Device) Wait(n Position) bool { return n > d.current }
func TestDonor(t *testing.T) {
 obj := Make()
 child := obj.Begin()
 child.Add(2)
 obj.Apply(child)
 x := child.Position()
 result := obj.Wait(x)
 if result { t.Fatal("unexpected") }
}
func TestRecipient(t *testing.T) {
 receiver := Make()
 handle := receiver.Wait(1000)
 if !handle { t.Fatal("unexpected") }
}
'''
    corpus, facts, producers, scalars = prepare(code, 'go')
    result = compose_witnesses(corpus, facts, producers + scalars)
    assert len(result['candidates']) == 2, result
    positive = next(row for row in result['candidates'] if row['relation']['offset'] == 1)
    assert positive['relation']['numeric_type']['aliases'][0]['name'] == 'Position'
    output = emit(corpus, [positive])
    assert not output['unsupported']
    if shutil.which('go'):
        for path, text in output['files'].items():
            (tmp_path / path).write_text(text)
        completed = subprocess.run(['go', 'test', './...'], cwd=tmp_path, env=dict(os.environ, GO111MODULE='off'),
                                   capture_output=True, text=True, timeout=60)
        assert completed.returncode == 0, completed.stdout + completed.stderr
