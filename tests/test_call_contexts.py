"""Source contexts are expression terms, not subject-specific operators."""
import ast
import json
import subprocess

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.call_contexts import ContextBudget, generate_call_contexts
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture(code, language='python'):
    path = 'test_terms.py' if language == 'python' else 'terms.test.ts'
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    for rank, test in enumerate(corpus['tests'].values(), 1):
        test['retrieval_rank'] = rank
    return corpus, frontend


PREFIX = '''events = []
def leaf(value):
    events.append(value)
    return value
def wrap(value, operation):
    return operation(value)

def test_source():
    assert wrap(leaf(2), lambda item: item + 1) == 3

'''


def target_candidates(corpus, frontend, name='test_target'):
    target = next(t['id'] for t in corpus['tests'].values() if t['name'] == name)
    return [c for c in generate_call_contexts(corpus, frontend)['candidates'] if c['base_test_id'] == target]


def test_source_callback_context_preserves_hole_and_requires_new_oracle():
    corpus, frontend = fixture(PREFIX + '''def test_target():
    result = leaf(5)
    assert result == 5
''')
    candidates = target_candidates(corpus, frontend)
    candidate = next(c for c in candidates if c['edits'][0]['after'] == 'wrap(leaf(5), lambda item: item + 1)')
    assert candidate['provenance']['context_free_names'] == ['wrap']
    assert candidate['oracle']['applicability'] == 'requires_independent_admission'
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    namespace = {}
    exec(output['files']['test_terms.py'], namespace)
    with pytest.raises(AssertionError):
        namespace[output['obligations'][0]['test_name']]()
    assert namespace['events'] == [5]
    # Source expectation is not silently recorded from the transformed subject.
    assert candidate['edits'][0]['after'].count('leaf(5)') == 1


def test_nested_target_argument_is_preserved_as_one_term():
    corpus, frontend = fixture(PREFIX + '''def test_target():
    result = [leaf(8), leaf(9)]
    assert result == [8, 9]
''')
    values = [c['edits'][0]['after'] for c in target_candidates(corpus, frontend)]
    assert 'wrap(leaf(8), lambda item: item + 1)' in values
    assert 'wrap(leaf(9), lambda item: item + 1)' in values


def test_callback_binding_does_not_hide_other_argument_capture():
    code = PREFIX.replace('wrap(leaf(2), lambda item: item + 1)', 'other(leaf(2), lambda item: item, item)')
    code = code.replace('def test_source():', 'def test_source():\n    item = 10')
    corpus, frontend = fixture(code + '''def test_target():
    item = 100
    assert leaf(5) == 5
''')
    assert not target_candidates(corpus, frontend)
    assert generate_call_contexts(corpus, frontend)['skipped']['context_test_local_capture']


def test_already_wrapped_source_is_not_wrapped_twice():
    corpus, frontend = fixture(PREFIX)
    assert not generate_call_contexts(corpus, frontend)['candidates']


def test_unrelated_callee_is_not_a_hole_match():
    corpus, frontend = fixture(PREFIX + '''def different(value): return value
def test_target():
    assert different(5) == 5
''')
    assert not target_candidates(corpus, frontend)


def test_cross_file_imported_context_is_closed_without_importing_test_helpers():
    sources = [Source('test_source.py', '''from library import leaf, wrap

def test_source():
    assert wrap(leaf(2), lambda value: value + 1) == 3
''', 'python'), Source('test_target.py', '''from library import leaf

def test_target():
    assert leaf(5) == 5
''', 'python')]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    candidate = target_candidates(corpus, frontend)[0]
    assert [item['name'] for item in candidate['imports']] == ['wrap']
    assert candidate['imports'][0]['module'] == 'library'


def test_typescript_expression_arrow_context_and_original_assertion_remain_source_owned():
    corpus, frontend = fixture('''const leaf = (x) => x;
const wrap = (x, op) => op(x);
test('source', () => { expect(wrap(leaf(2), item => item + 1)).toBe(3); });
test('target', () => { const result = leaf(8); expect(result).toBe(8); });
''', 'typescript')
    candidates = target_candidates(corpus, frontend, 'target')
    candidate = next(c for c in candidates if c['edits'][0]['after'] == 'wrap(leaf(8), item => item + 1)')
    assert candidate['provenance']['context_free_names'] == ['wrap']
    output = emit(corpus, [candidate])
    assert not output['unsupported']
    assert 'expect(result).toBe(8)' in output['files']['terms.test.ts']


def test_bounded_enumeration_is_deterministic_and_fair_across_tests():
    corpus, frontend = fixture(PREFIX + '\n'.join(f'def test_target_{n}():\n    assert leaf({n}) == {n}\n' for n in range(4)))
    budget = ContextBudget(max_candidates=3)
    result = generate_call_contexts(corpus, frontend, budget=budget)
    assert result == generate_call_contexts(corpus, frontend, budget=budget)
    assert len(result['candidates']) == 3
    assert len({c['base_test_id'] for c in result['candidates']}) == 3
    assert result['budget_exhausted']
