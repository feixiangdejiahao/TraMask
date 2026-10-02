"""Generic, authored fixtures; no task-specific sources or execution verdicts."""
import ast
import copy

import pytest

from relation_search.conditional_predicate_facts import analyze, analyze_source


def facts(code):
    return analyze_source(code)['facts']


def test_len_compared_to_container_is_conditionally_false():
    result = analyze_source('def test_case(xs):\n    assert len(xs) == []\n')
    fact, = result['facts']
    assert fact['normal_completion_value'] is False
    assert fact['operands'][0]['derivation'] == 'unshadowed_builtin_len_returns_int_on_normal_completion'
    assert fact['predicate'] == 'len(xs) == []'
    assert not fact['implies_test_invalid']
    assert result['test_validity'] == 'unconfirmed'
    assert 'evaluate normally' in fact['premise']


@pytest.mark.parametrize('code', [
    'def test_case(xs):\n    if False:\n        assert len(xs) == []\n',
    'def test_case(xs):\n    with pytest.raises(AssertionError):\n        assert len(xs) == []\n',
    'def test_case(xs):\n    try:\n        assert len(xs) == []\n    except AssertionError:\n        pass\n',
])
def test_guards_and_consumed_assertions_are_never_global_rejections(code):
    fact, = facts(code)
    assert fact['normal_completion_value'] is False
    assert fact['implies_test_invalid'] is False


@pytest.mark.parametrize('predicate', ['True == 1', '1 == 1.0', '1 != 1j', 'len(xs) == 0', '[] == []'])
def test_compatible_types_do_not_create_constant_facts(predicate):
    assert not facts('def test_case(xs):\n    assert ' + predicate + '\n')


@pytest.mark.parametrize('predicate', ["'x' == []", '() != {}', 'None == 0', '{1} != [1]', '-1 == ()'])
def test_known_disjoint_builtin_categories(predicate):
    fact, = facts('assert ' + predicate)
    assert fact['normal_completion_value'] is ('!=' in predicate)


@pytest.mark.parametrize('predicate', ['custom == []', 'custom() == []', 'int(custom) == []',
                                       'len(xs) < []', 'len(xs) == [] == []', 'len(*xs) == []'])
def test_user_equality_calls_and_unsupported_shapes_remain_unknown(predicate):
    result = analyze_source('def test_case(xs, custom):\n    assert ' + predicate + '\n')
    assert not result['facts'] and result['unknowns']


@pytest.mark.parametrize('prefix', [
    'len = lambda xs: []\n', 'from other import len\n', 'from other import size as len\n',
    'import other as len\n', 'from other import *\n',
    'def len(xs):\n    return []\n', 'class len:\n    pass\n',
    'globals()["len"] = lambda xs: []\n', 'exec("len = replacement")\n',
    'builtins.len = other\n', 'monkeypatch.setattr("builtins.len", other)\n',
])
def test_visible_global_import_and_dynamic_shadowing_prevents_len_fact(prefix):
    result = analyze_source(prefix + 'def test_case(xs):\n    assert len(xs) == []\n')
    assert not result['facts']
    assert result['builtin_context']['blockers']


@pytest.mark.parametrize('code', [
    'def test_case(xs, len):\n    assert len(xs) == []\n',
    'def test_case(xs):\n    assert len(xs) == []\n    len = other\n',
    'def test_case(xs):\n    for len in xs:\n        assert len(xs) == []\n',
    'def test_case(xs):\n    with context() as len:\n        assert len(xs) == []\n',
    'def test_case(xs):\n    try:\n        go()\n    except Exception as len:\n        assert len(xs) == []\n',
    'def test_case(xs):\n    match xs:\n        case {"name": len}:\n            assert len(xs) == []\n',
    'def test_case(xs):\n    global len\n    assert len(xs) == []\n',
    'def outer(len):\n    def test_case(xs):\n        assert len(xs) == []\n',
])
def test_all_lexical_binding_forms_are_conservatively_unknown(code):
    assert not facts(code)


def test_imported_builtin_alias_is_unsupported_not_assumed():
    assert not facts('from builtins import len as size\nassert size(xs) == []')
    assert not facts('from builtins import len\nassert len(xs) == []')


def test_unrelated_len_shadow_is_conservative_but_literal_fact_survives():
    result = analyze_source('def unrelated(len):\n    pass\nassert len(xs) == []\nassert 1 == []')
    assert [f['predicate'] for f in result['facts']] == ['1 == []']


def test_exact_utf8_spans_and_explicit_selection():
    code = 'label = "猫"; assert len(xs) == []\nassert len(xs) != []\n'
    raw = code.encode()
    expression = b'len(xs) != []'
    start = raw.index(expression)
    result = analyze_source(code, path='tests/test_unicode.py', predicate_spans=[dict(
        check_id='Q7', path='tests/test_unicode.py', start_byte=start, end_byte=start + len(expression))])
    fact, = result['facts']
    assert fact['check_id'] == 'Q7' and fact['normal_completion_value'] is True
    assert raw[fact['predicate_span']['start_byte']:fact['predicate_span']['end_byte']] == expression


def test_inexact_span_does_not_match_another_expression():
    result = analyze_source('assert len(xs) == []', predicate_spans=[dict(start_byte=8, end_byte=19)])
    assert not result['facts']
    assert result['unknowns'][0]['reason'] == 'predicate_span_not_exact_expression'


def test_unsupported_language_parse_and_budget_remain_unknown():
    assert analyze_source('assert len(xs) == []', language='typescript')['status'] == 'unsupported_language'
    assert analyze_source('not Python !')['status'] == 'unknown_python_parse'
    assert analyze_source('assert 1 == []', max_source_bytes=3)['status'] == 'unknown_source_budget'


def test_known_literal_disjointness_agrees_with_python_without_custom_objects():
    literals = ['True', '0', '1.5', '2j', '"a"', 'b"a"', 'None', '[]', '()', '{}', '{1}']
    for left in literals:
        for right in literals:
            for operator in ('==', '!='):
                predicate = f'{left} {operator} {right}'
                for fact in facts('assert ' + predicate):
                    lhs, rhs = ast.literal_eval(left), ast.literal_eval(right)
                    expected = lhs == rhs if operator == '==' else lhs != rhs
                    assert fact['normal_completion_value'] is expected


def test_compact_adapter_only_attaches_selected_modified_validation_predicates():
    from anchor_retrieval.syntax import Source
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    from relation_search.compact_test_obligations import analyze as compact_analyze

    code = '''def helper(xs):
    assert len(xs) == []
def test_case():
    helper([])
    assert len([]) == 0
'''
    frontend = extract_frontend([Source('tests/test_authored.py', code, 'python')])
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus['tests']))
    offset = code.encode().index(b'len([]) == 0') + len(b'len([]) == ')
    candidate = dict(id='authored', base_test_id=test_id, imports=[], source_test_ids=[], edits=[dict(
        span=dict(path='tests/test_authored.py', start_byte=offset, end_byte=offset + 1),
        before='0', after='[]', role='expected')])
    compact = compact_analyze(corpus, frontend, candidate)
    snapshot = copy.deepcopy((corpus, frontend, candidate, compact))
    result = analyze(corpus, frontend, candidate, source_analysis=compact)
    assert result['status'] == 'analyzed' and len(result['facts']) == 2
    assert all(f['check_id'] in compact['obligations'] for f in result['facts'])
    assert all(f['normal_completion_value'] is False for f in result['facts'])
    assert (corpus, frontend, candidate, compact) == snapshot
    wrong = copy.deepcopy(compact)
    next(iter(wrong['sources'].values()))['code'] += ' '
    result = analyze(corpus, frontend, candidate, source_analysis=wrong)
    assert result['status'] == 'unknown_source_binding' and not result['facts']
