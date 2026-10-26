"""Independent weak-to-strong observation example; no subject is executed."""
import json

from generic_composition.corpus import build_corpus
from generic_composition.emitter import emit
from prototypes.assertion_window_generation.generate import generate as predicate_grouped
from prototypes.assertion_window_generation.predicate_free import Budget, generate, gate_evidence


CODE = '''def test_a():
    box = Box()
    box.put(4)
    assert box is not None

def test_b():
    box = Box()
    box.put(4)
    assert box.peek() == 4

def test_c():
    box = Box()
    box.put(9)
    assert box is not None
'''


def test_full_driver_can_transport_stronger_observation_without_predicate_group(tmp_path):
    (tmp_path / 'test_strength.py').write_text(CODE)
    corpus = build_corpus(tmp_path, 'python')
    original = predicate_grouped(corpus)
    assert original['counts']['groups'] == 2
    assert original['counts']['attempted_triples'] == 0
    generated = generate(corpus)
    assert generated['budget'] == original['budget']
    assert generated['counts']['groups'] == 1
    assert generated['counts']['attempted_triples'] == 6
    wanted = 'box = Box()\n    box.put(9)\n    assert box.peek() == 9'
    proposals = [c for c in generated['candidates'] if c['edits'][0]['after'] == wanted]
    assert proposals and not emit(corpus, proposals)['unsupported']
    assert proposals[0]['oracle']['semantic_status'] == 'requires_admission'
    evidence, candidates = gate_evidence(corpus, generated, 'put stores a value retrievable by peek.')
    assert 'does not establish its oracle' in evidence['grouping_policy']
    json.dumps([generated, evidence, candidates])
    assert generated == generate(corpus)


def test_predicate_free_keeps_attempt_and_output_budgets(tmp_path):
    (tmp_path / 'test_strength.py').write_text(CODE)
    corpus = build_corpus(tmp_path, 'python')
    small = generate(corpus, Budget(max_attempts=1, max_candidates=1))
    assert small['counts']['attempted_triples'] <= 1
    assert small['counts']['candidates'] <= 1
