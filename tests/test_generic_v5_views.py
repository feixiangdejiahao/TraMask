"""Unified views use invented tests and existing static corpus facts only."""
import json

from anchor_retrieval.syntax import Source, child, walk
from generic_composition.corpus import build_corpus
from generic_composition.terms import from_source, render
from prototypes.unified_view_test_analogy_v05.views import compose_views, observer_keys
from prototypes.unified_view_test_analogy_v05.generate import Budget, gate_evidence, generate
from generic_composition.emitter import emit
from generic_composition.gate import presentation, selection_candidates


def records(tmp_path, bodies):
    text = '\n'.join(f'def test_{name}():\n    ' + body.replace('\n', '\n    ')
                     for name, body in zip('ABC', bodies)) + '\n'
    (tmp_path / 'test_views.py').write_text(text)
    data = build_corpus(tmp_path, 'python')
    source = Source('test_views.py', text, 'python')
    rows, facts = [], []
    for test in sorted(data['tests'].values(), key=lambda t: t['span']['start_byte']):
        node = next(n for n in walk(source.root) if n.type == 'function_definition'
                    and n.start_byte == test['definition_span']['start_byte'])
        rows.append({'tree': from_source(source, child(node, 'body')), 'test': test})
        facts.append([a for a in data['capsules'] if a['test_id'] == test['id']])
    return rows, facts, data


def test_raw_deletion_remains_a_candidate_when_full_alignment_has_no_embedding(tmp_path):
    rows, facts, _ = records(tmp_path, ['setup(1)\nassert f(3) == 6',
        'assert f(3) == 6', 'setup(9)\nassert f(5) == 10'])
    output = compose_views(*rows, capsules=facts)
    raw = output[0]
    assert raw.status == 'hypothesis' and raw.provenance['view'] == 'raw'
    assert render(raw.output) == 'assert f(5) == 10'
    assert raw.provenance['analogy']['omitted_holes']
    assert all(raw.provenance['checks'].values())
    assert any(r.reason == 'missing_anchor' for r in output)


def test_precise_actual_observer_recovers_added_assertion_with_target_setup(tmp_path):
    rows, facts, _ = records(tmp_path, ['assert f(1) == 2',
        'assert f(1) == 2\nassert metadata() == 3', 'arg = 5\nassert f(arg) == 10'])
    output = compose_views(*rows, capsules=facts)
    matches = [r for r in output if r.status == 'hypothesis']
    assert len(matches) == 1
    result = matches[0]
    assert result.provenance['view'] == 'aligned_observer'
    assert render(result.output) == 'arg = 5\n    assert f(arg) == 10\n    assert metadata() == 3'
    assert all(result.provenance['checks'].values())


def test_field_projection_distinguishes_observers_with_same_upstream_factory(tmp_path):
    rows, facts, _ = records(tmp_path, ['x = make(1)\nassert x.left == 2',
        'x = make(1)\nassert x.left == 2\nassert x.right == 3',
        'arg = 5\nx = make(arg)\nassert x.left == 10'])
    result = next(r for r in compose_views(*rows, capsules=facts) if r.status == 'hypothesis')
    assert result.provenance['view'] == 'aligned_observer'
    assert render(result.output) == 'arg = 5\n    x = make(arg)\n    assert x.left == 10\n    assert x.right == 3'
    evidence = result.provenance['observer_evidence']['B']
    assert evidence[0]['actual_frontier'] != evidence[1]['actual_frontier']


def test_expected_constants_are_not_observer_anchor_keys(tmp_path):
    rows, facts, _ = records(tmp_path, ['assert f(1) == 2', 'assert f(1) == 333', 'assert f(4) == 99'])
    keys = [observer_keys(row, f)[0] for row, f in zip(rows, facts)]
    assert keys[0] == keys[1] == keys[2]


def test_changed_observation_uses_shape_fallback_instead_of_being_forbidden(tmp_path):
    rows, facts, _ = records(tmp_path, ['assert f(1) == 2',
        'assert wrap(f(1)) == [2]', 'arg = 3\nassert f(arg) == 6'])
    result = next(r for r in compose_views(*rows, capsules=facts) if r.status == 'hypothesis')
    assert result.provenance['view'] == 'aligned_fallback'
    assert result.provenance['preferred_observer_attempt']['reason'] == 'missing_anchor'
    assert render(result.output) == 'arg = 3\n    assert wrap(f(arg)) == [6]'


def test_same_program_from_two_views_is_deduplicated(tmp_path):
    rows, facts, _ = records(tmp_path, ['assert f(1) == 2',
        'assert f([1]) == [2]', 'assert f(3) == 6'])
    output = compose_views(*rows, capsules=facts)
    hypotheses = [r for r in output if r.status == 'hypothesis']
    assert len(hypotheses) == 1
    assert hypotheses[0].provenance['view'] == 'raw'
    assert render(hypotheses[0].output) == 'assert f([3]) == [6]'


def test_driver_uses_one_triple_budget_for_all_views_and_emits_raw_deletion(tmp_path):
    _, _, data = records(tmp_path, ['setup(1)\nassert f(3) == 6',
        'assert f(3) == 6', 'setup(9)\nassert f(5) == 10'])
    generated = generate(data)
    matches = [p for p in generated['candidates'] if p['edits'][0]['after'] == 'assert f(5) == 10']
    assert matches and matches[0]['composition_view'] == 'raw'
    assert matches[0]['alignment']['alignment'] == {}
    assert matches[0]['alignment']['gap_order'] == 'raw'
    assert 'C_residual_slots_preserved_exactly' not in matches[0]['provenance']['checks']
    assert emit(data, [matches[0]])['unsupported'] == []
    small = generate(data, Budget(max_attempts=2, max_candidates=1))
    assert small['counts']['attempted_triples'] <= 2
    assert small['counts']['attempted_views'] <= 6
    assert small['counts']['candidates'] <= 1
    assert small == generate(data, Budget(max_attempts=2, max_candidates=1))
    json.dumps(generated)


def test_driver_additional_observer_and_gate_distinguish_the_views(tmp_path):
    _, _, data = records(tmp_path, ['assert f(1) == 2',
        'assert f(1) == 2\nassert metadata() == 3', 'arg = 5\nassert f(arg) == 10'])
    generated = generate(data)
    matches = [p for p in generated['candidates'] if p['edits'][0]['after'] ==
               'arg = 5\n    assert f(arg) == 10\n    assert metadata() == 3']
    assert matches
    assert matches[0]['composition_view'] == 'aligned_observer'
    assert emit(data, [matches[0]])['unsupported'] == []
    evidence, candidates = gate_evidence(data, generated, 'Ordinary function contract')
    shown = presentation(evidence, selection_candidates(candidates, 'ordinal_v1'))
    assert 'Only aligned views claim exact unmatched C statement retention' in evidence['composition_policy']
    assert 'Raw views may delete source operations' in evidence['composition_policy']
    assert all('composition_view' in p for p in shown['candidates'])
    assert all(p['rule_id'] in shown['evidence']['analogy_sources'] for p in shown['candidates'])
    json.dumps(shown)
