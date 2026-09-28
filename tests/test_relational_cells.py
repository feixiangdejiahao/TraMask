from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.cells import CellBudget, generate_cells, merge_candidates, recover_rows, annotate_novelty
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture(code):
    frontend = extract_frontend([Source('test_samples.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    for i, test in enumerate(corpus['tests'].values()):
        test['retrieval_rank'] = i + 1
    return corpus, frontend


def test_observation_relative_joint_cells_generate_executable_minimal_edits():
    corpus, frontend = fixture('''
def choose(a, b):
    return a + b
def test_first():
    result = choose(1, 10)
    assert result > 0
def test_second():
    result = choose(2, 20)
    assert result > 0
''')
    found = generate_cells(corpus, frontend)
    assert len(found['candidates']) == 2
    emitted = emit(corpus, found['candidates'])
    assert not emitted['unsupported']
    code = emitted['files']['test_samples.py']
    assert 'choose(1, 20)' in code
    assert 'choose(2, 10)' in code
    namespace = {}
    exec(compile(code, 'test_samples.py', 'exec'), namespace)
    for name, value in namespace.items():
        if name.startswith('test_'):
            value()
    assert all(len(c['edits']) == 1 for c in found['candidates'])


def test_different_observation_does_not_cover_or_supply_joint_cell():
    corpus, frontend = fixture('''
def test_first():
    result = choose(1, 10)
    assert result.left > 0
def test_second():
    result = choose(2, 20)
    assert result.right > 0
''')
    found = generate_cells(corpus, frontend)
    assert not found['candidates']
    assert found['counts']['groups'] == 2


def test_expected_values_never_become_input_coordinates():
    corpus, frontend = fixture('''
def test_first():
    expected = 10
    result = choose(1, expected)
    assert result == expected
''')
    rows, _, _ = recover_rows(corpus, frontend)
    assert rows
    assert all(10 not in row['coordinates'].values() for row in rows)


def test_deterministic_fair_merge_deduplicates_identical_source_edits():
    a = {'id': 'a', 'kind': 'one', 'base_test_id': 'x', 'edits': [{'after': '1'}]}
    b = {'id': 'b', 'kind': 'one', 'base_test_id': 'x', 'edits': [{'after': '2'}]}
    c = {'id': 'c', 'kind': 'two', 'base_test_id': 'x', 'edits': [{'after': '3'}]}
    assert [x['id'] for x in merge_candidates([a, b], [a, c], limit=2)] == ['a', 'c']


def test_exact_value_swap_already_observed_at_same_q_is_not_new_relation():
    corpus, frontend = fixture('''
def test_first():
    result = choose(1)
    assert result > 0
def test_second():
    result = choose(2)
    assert result > 0
''')
    call = next(c for c in frontend['calls'] if c['callee'] == 'choose')
    candidate = {'id': 'swap', 'base_test_id': call['test_id'], 'kind': 'aligned_input_substitution',
                 'edits': [{'span': call['arguments'][0]['span'], 'before': '1', 'after': '2'}]}
    result = annotate_novelty(corpus, frontend, [candidate])
    assert result[0]['static_novelty']['status'] == 'already_present_source_tuple'
    assert not result[0]['static_novelty']['checked_coverage']
