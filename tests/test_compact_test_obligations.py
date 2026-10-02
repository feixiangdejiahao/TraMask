"""Authored source fixtures only: no providers, runtime verdicts or labels."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.compact_test_obligations import analyze, render, source_text


def prepared(code, language='python', extra=None, before=None, after=None, **limits):
    path = {'python': 'tests/test_compact.py', 'go': 'compact_test.go',
            'typescript': 'tests/compact.test.ts'}[language]
    sources = [Source(path, code, language)] + [Source(p, c, language) for p, c in (extra or {}).items()]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus['tests']))
    edits = []
    if before is not None:
        start = code.encode().index(before.encode(), corpus['tests'][test_id]['span']['start_byte'])
        edits = [dict(span=dict(path=path, start_byte=start, end_byte=start + len(before.encode())),
                      before=before, after=after, role='input')]
    candidate = dict(id='authored', base_test_id=test_id, edits=edits, imports=[], source_test_ids=[])
    snapshot = copy.deepcopy((corpus, frontend, candidate))
    result = analyze(corpus, frontend, candidate, **limits)
    assert (corpus, frontend, candidate) == snapshot
    return result


def recursive(result):
    return [row for row in result['sccs'] if row['recursive']]


def test_direct_recursion_has_one_source_site_and_exact_finite_bindings():
    result = prepared('''def check(xs):
    assert len(xs) >= 0
    if xs:
        check(xs[1:])
def test_case():
    check([1, 2, 3])
''')
    assert result['status'] == 'complete'
    assert len(result['units']) == 2 and len(result['calls']) == 2
    assert len(result['obligations']) == 1 and len(recursive(result)) == 1
    edge = next(row for row in result['calls'].values() if row['caller'] == row['callee'])
    assert source_text(result, edge['arguments'][0]['actual']) == 'xs[1:]'
    assert source_text(result, edge['guards'][0]['condition']) == 'xs'
    assert not result['alarm_eligible'] and result['semantic_validity'] == 'unconfirmed'
    assert not result['coverage']['termination_proved']


def test_mutual_recursion_preserves_all_checks_and_no_unrolled_contexts():
    result = prepared('''def first(n):
    assert n != -1
    if n:
        second(n-1)
def second(n):
    assert n != -2
    if n:
        first(n-1)
def test_case():
    first(3)
    first(8)
''')
    assert result['status'] == 'complete'
    assert len(result['units']) == 3 and len(result['calls']) == 4
    assert len(result['obligations']) == 2
    assert len(recursive(result)[0]['members']) == 2
    assert len(recursive(result)[0]['internal_calls']) == 2
    assert 'call_path' not in json.dumps(result)


def test_renderer_contains_complete_source_once_and_uses_byte_refs():
    code = '''def check(value):
    assert value == "猫"
def test_case():
    check("猫")
    check("猫")
'''
    result = prepared(code)
    output = render(result)
    assert output.count('def check(value):') == 1
    assert output.count('assert value == "猫"') == 1
    assert output.count('def test_case():') == 1
    check = next(iter(result['obligations'].values()))
    assert source_text(result, check['predicate']) == 'value == "猫"'
    assert 'source coverage' in output.lower()
    assert result == prepared(code)


def test_guarded_go_failure_excludes_its_own_failing_branch_from_precondition():
    result = prepared('''package example
import "testing"
func check(t *testing.T, value int) {
 if value > 0 { if value != 1 {t.Fatal(value)} }
}
func TestCase(t *testing.T) {check(t, 1); check(t, 2)}
''', 'go')
    assert result['status'] == 'complete'
    checks = [row for row in result['obligations'].values() if row['kind'] == 'negated_failure_guard']
    assert len(checks) == 1
    assert source_text(result, checks[0]['predicate']) == 'value != 1'
    assert [source_text(result, row['condition']) for row in checks[0]['guards']] == ['value > 0']


def test_expected_exception_keeps_dormant_inner_assert_and_post_exit_check_separate():
    result = prepared('''import pytest
def explode():
    raise ValueError('intentional')
def test_case():
    with pytest.raises(ValueError, match='intentional'):
        explode()
        assert 2 == []
    assert 1 == 1
''')
    assert result['status'] == 'complete'
    exception_id, exception = next((key, row) for key, row in result['obligations'].items()
                                   if row['kind'] == 'expected_exception')
    dormant = next(row for row in result['obligations'].values()
                   if source_text(result, row['at']) == 'assert 2 == []')
    after = next(row for row in result['obligations'].values()
                 if source_text(result, row['at']) == 'assert 1 == 1')
    assert dormant['exception_regions'] == [exception_id]
    assert after['exception_regions'] == []
    assert source_text(result, exception['expected']) == 'ValueError'
    assert "match='intentional'" in source_text(result, exception['at'])
    assert exception['requires'] == 'matching_exception_adapter_exit'
    call = next(row for row in result['calls'].values() if source_text(result, row['at']) == 'explode()')
    assert call['exception_regions'] == [exception_id]


def test_exception_consumption_can_cross_a_helper_edge_without_invented_truth():
    result = prepared('''import pytest
def check(value):
    assert value == 1
def test_case():
    with pytest.raises(AssertionError):
        check(2)
''')
    edge = next(iter(result['calls'].values()))
    assert len(edge['exception_regions']) == 1
    helper = next(row for row in result['obligations'].values() if row['kind'] == 'assert_expression')
    assert helper['exception_regions'] == []  # inherited dynamically through the call edge
    assert result['semantic_validity'] == 'unconfirmed'
    assert 'including a helper or' in result['semantics']


def test_production_assertions_and_body_are_not_oracle_evidence():
    result = prepared('from library import compute\ndef test_case():\n    assert compute(2) == 1\n',
                      extra={'library.py': 'def compute(n):\n    assert PRODUCTION_ASSERT\n    return PRODUCTION_BODY\n'})
    wire = json.dumps(result)
    assert result['status'] == 'complete'
    assert len(result['units']) == len(result['obligations']) == 1
    assert 'PRODUCTION_ASSERT' not in wire and 'PRODUCTION_BODY' not in wire
    assert 'def compute(n):' in wire
    assert any(row['kind'] == 'resolved_production_or_unproved_validation'
               and row['validation_provenance'] == 'not_established' for row in result['boundaries'])


def test_opaque_callback_keeps_source_and_does_not_borrow_production_arguments():
    result = prepared('''from engine import invoke
def check(value):
    assert value == 1
def test_case():
    invoke(check)
''', extra={'engine.py': 'def invoke(callback):\n    callback(PRODUCTION_CALLBACK_ARGUMENT)\n'})
    assert result['status'] == 'partial'
    assert len(result['obligations']) == 1
    assert any(row['kind'] == 'function_value_argument' for row in result['entries'])
    assert any(row['code'] == 'callback_invocation_binding_unproved' for row in result['unknowns'])
    assert 'PRODUCTION_CALLBACK_ARGUMENT' not in json.dumps(result)


def test_nested_callback_source_bytes_are_never_duplicated():
    result = prepared('''from engine import invoke
def test_case():
    def check(value):
        assert value == 1
    invoke(check)
''')
    assert result['status'] == 'partial'
    output = render(result)
    assert output.count('def check(value):') == 1
    assert output.count('assert value == 1') == 1


def test_imported_test_helper_and_fixture_dependency_preserve_exact_source():
    result = prepared('''import pytest
from tests.helpers import check
EXPECTED = 2
@pytest.fixture
def seed():
    assert EXPECTED > 0
    return EXPECTED
def test_case(seed):
    check(seed)
''', extra={'tests/helpers.py': 'def check(value):\n    assert value == 2\n'})
    assert result['status'] == 'complete'
    assert len(result['obligations']) == 2
    assert any(row['kind'] == 'source_pytest_fixture' for row in result['entries'])
    output = render(result)
    assert '@pytest.fixture' in output and 'EXPECTED = 2' in output
    assert 'from tests.helpers import check' in output
    assert output.count('assert value == 2') == 1


@pytest.mark.parametrize('code,reason', [
    ('def test_case(seed):\n    assert seed == 1\n', 'fixture_source_or_binding_unproved'),
    ('def check(a,b):\n    assert a == b\ndef test_case():\n    check(1)\n', 'validator_binding_unproved'),
    ('def test_case():\n    unknown.inspect()\n', 'validator_dispatch_unproved'),
])
def test_unsupported_provenance_and_bindings_stay_explicit(code, reason):
    result = prepared(code)
    assert result['status'] == 'partial'
    assert any(row['code'] == reason for row in result['unknowns'])
    assert not result['coverage']['source_sites_complete']


def test_modified_fixed_test_is_complete_and_original_offsets_are_separate():
    result = prepared('def test_case():\n    value = 1\n    assert value == 1\n',
                      before='value = 1', after='value = 1000')
    root = result['units'][result['root']]
    assert source_text(result, root['at']) == 'def test_case():\n    value = 1000\n    assert value == 1'
    assert source_text(result, result['edits'][0]['modified']) == 'value = 1000'
    assert result['edits'][0]['original']['end_byte'] < result['edits'][0]['modified']['end']


def test_unit_budget_retains_unknown_and_does_not_claim_semantic_coverage():
    result = prepared('def check(x):\n    assert x == 1\ndef test_case():\n    check(1)\n', max_units=1)
    assert result['status'] == 'partial'
    assert any(row['code'] == 'validator_unit_budget' for row in result['unknowns'])
    assert not result['alarm_eligible']


def test_try_except_and_early_return_remain_source_controls_not_reachability_proofs():
    result = prepared('''def check(value):
    if value < 0:
        return
    try:
        assert value == 1
    except AssertionError:
        assert value == 2
    finally:
        assert value > 0
def test_case():
    check(2)
''')
    assert result['status'] == 'complete'
    assert len(result['obligations']) == 3
    handler = next(row for row in result['obligations'].values()
                   if source_text(result, row['at']) == 'assert value == 2')
    finalizer = next(row for row in result['obligations'].values()
                     if source_text(result, row['at']) == 'assert value > 0')
    assert any(row['kind'] == 'except_clause' for row in handler['guards'])
    assert any(row['kind'] == 'finally_clause' for row in finalizer['guards'])
    assert 'if value < 0:\n        return' in render(result)
    assert not result['coverage']['reachability_proved']


def test_typescript_recursive_native_assertion_has_finite_source_representation():
    code = "import {expect,test} from 'vitest';function check(xs:number[]){expect(xs.length).toBe(0);if(xs.length){check(xs.slice(1));}}test('case',()=>{check([1,2,3]);});"
    result = prepared(code, 'typescript')
    assert result['status'] == 'complete'
    assert len(result['obligations']) == 1 and len(recursive(result)) == 1
    edge = next(row for row in result['calls'].values() if row['caller'] == row['callee'])
    assert source_text(result, edge['arguments'][0]['actual']) == 'xs.slice(1)'


def test_unmodeled_autouse_fixture_is_explicit_with_its_full_source():
    result = prepared('''import pytest
@pytest.fixture(autouse=True)
def initialize():
    assert setup_value == 1
def test_case():
    assert result == 2
''')
    assert result['status'] == 'partial'
    assert any(row['code'] == 'implicit_fixture_lifecycle_unproved' for row in result['unknowns'])
    assert 'assert setup_value == 1' in render(result)


def test_unknown_root_decorator_and_fixture_cycle_are_explicit():
    decorated = prepared('@decorate\ndef test_case():\n    assert value == 1\n')
    cyclic = prepared('''import pytest
@pytest.fixture
def left(right):
    return right
@pytest.fixture
def right(left):
    return left
def test_case(left):
    assert left == 1
''')
    assert decorated['status'] == cyclic['status'] == 'partial'
    assert any(row['code'] == 'root_decorator_dispatch_unproved' for row in decorated['unknowns'])
    assert any(row['code'] == 'fixture_dependency_cycle' for row in cyclic['unknowns'])
