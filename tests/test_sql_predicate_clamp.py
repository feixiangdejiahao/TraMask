import ast
import copy
import sqlite3

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import sql_predicate_clamp as relation
from relation_search.oracle import preview


def fixture(code, path='tests/test_conditions.py'):
    frontend = extract_frontend([Source(path, code, 'python', 'repository')])
    corpus = to_emitter_corpus(frontend)
    for rank, test in enumerate(corpus['tests'].values()):
        test['retrieval_rank'] = rank
    return corpus, frontend


def generate(code):
    corpus, frontend = fixture(code)
    original = copy.deepcopy((corpus, frontend))
    result = relation.generate(corpus, frontend, 'Public SQLite expression contract.')
    assert (corpus, frontend) == original
    return result, corpus, frontend


@pytest.mark.parametrize('operator,function', [('<', 'min'), ('>', 'max'), ('<=', 'max'), ('>=', 'min')])
def test_numeric_null_predicate_law_on_sqlite(operator, function):
    # This tests the stated bounded law, not the project or any generated test.
    values = [None, -(2**63), -10, -1, -0.5, 0, 0.5, 1, 9.999, 10, 11, 2**63-1]
    with sqlite3.connect(':memory:') as db:
        db.execute('create table values_under_test(x)')
        db.executemany('insert into values_under_test values (?)', [(x,) for x in values])
        for bound in [-(2**63), -10, -1, 0, 1, 10, 2**63-1]:
            source = f'x {operator} {bound}'
            rewritten = relation.rewrite(source)
            assert rewritten['function'] == function
            rows = db.execute(f'select {source}, {rewritten["value_after"]} from values_under_test').fetchall()
            assert all(left == right for left, right in rows)
            assert rows[0] == (None, None)


def test_text_affinity_is_a_real_counterexample_to_unconditional_equivalence():
    with sqlite3.connect(':memory:') as db:
        db.execute('create table data(x TEXT)')
        db.execute("insert into data values ('1')")
        # A column's text affinity coerces the integer; a scalar result does not.
        assert db.execute('select x > 10, max(x, 10) > 10 from data').fetchone() == (0, 1)


@pytest.mark.parametrize('value', ['x = 1', 'x < 1 and y > 2', 'x + 1 < 2', 'a.x < 2',
    'select x < 2', 'min(x, 1) < 2', 'x < 1.0', 'x < 0x10', 'x < ?',
    'x < 9223372036854775808', 'x < -9223372036854775809', 'x < '+'0'*5000, 1])
def test_only_bounded_complete_predicate_grammar(value):
    assert relation.rewrite(value) is None


def test_unknown_method_argument_is_only_a_source_hypothesis_and_preserves_whole_test():
    code = '''import pytest
@pytest.mark.parametrize("number", [1, 20])
def test_rule(db, number):
    label = "α"
    db.set_rule("items", predicate="score < +10")
    with pytest.raises(ValueError):
        db.insert({"score": number})
    assert db.count() == 0
    assert label == "α"
'''
    result, corpus, _ = generate(code)
    assert result['total_candidates'] == 1
    candidate = result['candidates'][0]
    assert candidate['source_evidence']['consumer_binding'] is None
    assert candidate['source_evidence']['dialect_status'] == 'unproved'
    assert candidate['source_evidence']['oracle_preservation_proved'] is False
    before = candidate['source_evidence']['original_test']['text']
    after = preview(corpus, candidate)
    assert after == before.replace('"score < +10"', "'min(score, +10) < +10'")
    assert after.startswith('@pytest.mark.parametrize') and after.endswith('assert label == "α"')
    emitted = emit(corpus, [candidate])
    assert not emitted['unsupported']
    assert "'min(score, +10) < +10'" in next(iter(emitted['files'].values()))


@pytest.mark.parametrize('statement', [
    'assert consume("x < 10")',
    'expected = consume("x < 10")\n    assert actual() == expected',
    'with pytest.raises(ValueError, match="x < 10"):\n        consume("ignored")',
    'expression = "x < 10"\n    consume(expression)',
    'consume(["x < 10"])',
    'consume("x < " "10")',
    'def helper():\n        return consume("x < 10")\n    helper()',
    'callback = lambda: consume("x < 10")\n    callback()',
])
def test_oracle_nested_and_indirect_literal_regions_are_not_inputs(statement):
    code = 'import pytest\nfrom example import consume, actual\ndef test_rule():\n    '+statement+'\n    assert True\n'
    assert not generate(code)[0]['candidates']


def test_decorator_literal_is_unchanged_and_not_a_candidate():
    code = '''import pytest
@pytest.mark.parametrize("predicate", ["x < 10"])
def test_rule(predicate):
    assert predicate
'''
    assert not generate(code)[0]['candidates']


def test_api_field_test_and_module_renaming_does_not_select_cases():
    code = '''from other_library import configure
def test_arbitrary():
    configure(rule="renamed >= -7")
    assert True
'''
    result, _, _ = generate(code)
    assert result['total_candidates'] == 1
    evidence = result['catalog'][0]
    assert evidence['predicate']['value_after'] == 'min(renamed, -7) >= -7'
    assert evidence['consumer_status'] == 'source_binding_hint'


def test_source_order_limit_origin_complete_spans_and_metadata_integrity():
    code = 'from example import configure\ndef test_late():\n'
    code += ''.join(f'    configure("x < {i}")\n' for i in range(20))
    code += '    assert True\ndef test_first():\n    configure("x > -1")\n    assert True\n'
    corpus, frontend = fixture(code)
    for test in corpus['tests'].values():
        test['retrieval_rank'] = 0 if test['name'] == 'test_first' else 9
    result = relation.generate(corpus, frontend, 'Unrelated identifiers do not filter this grammar.')
    assert result['total_candidates'] == 21 and len(result['candidates']) == 16
    assert result['candidates'][0]['source_evidence']['predicate']['value_before'] == 'x > -1'
    for bad in [-1, 17, True, 0.5]:
        with pytest.raises(ValueError, match='limit'):
            relation.generate(corpus, frontend, '', limit=bad)
    changed = copy.deepcopy(corpus); changed['sources']['tests/test_conditions.py']['code'] += '\n'
    with pytest.raises(ValueError, match='frontend_source_mismatch'):
        relation.generate(changed, frontend, '')
    truncated = copy.deepcopy(corpus)
    for test in truncated['tests'].values():
        test['span']['end_byte'] -= 1
    assert not relation.generate(truncated, frontend, '')['candidates']
    corpus['sources']['tests/test_conditions.py']['origin'] = 'trajectory'
    assert not relation.generate(corpus, frontend, '')['candidates']
    assert relation.generate({'language': 'go'}, {}, '')['status'] == 'language_unsupported'
