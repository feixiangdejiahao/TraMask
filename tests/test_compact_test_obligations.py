"""Authored source fixtures only: no providers, runtime verdicts or labels."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.compact_test_obligations import analyze, render, source_excerpt, source_text


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


def test_global_typescript_throw_matchers_are_retained_with_unproved_identity():
    result = prepared("""test('exceptions', () => {
    expect(() => parse('bad')).toThrow(TypeError);
    expect(() => parse('good')).not.toThrow();
});
""", 'typescript')
    checks = list(result['obligations'].values())
    assert len(checks) == 2
    assert [source_text(result, row['predicate']) for row in checks] == [
        "expect(() => parse('bad')).toThrow(TypeError)",
        "expect(() => parse('good')).not.toThrow()",
    ]
    assert all(row['adapter_identity'] == 'unproved' for row in checks)
    assert result['status'] == 'partial'
    assert any(row['code'] == 'assertion_adapter_identity_unproved' for row in result['unknowns'])
    assert '.not.toThrow()' in render(result)


def test_import_aliased_throw_matcher_retains_exact_predicate_and_identity():
    result = prepared("""import {test, expect as verify} from 'vitest';
test('exceptions', () => {
    verify(() => parse('bad')).toThrow(TypeError);
    verify(() => parse('good')).not.toThrow();
});
""", 'typescript')
    checks = list(result['obligations'].values())
    assert len(checks) == 2
    assert all(row['adapter_identity'] == 'proved' for row in checks)
    assert source_text(result, checks[1]['predicate']) == "verify(() => parse('good')).not.toThrow()"


def test_unbound_callback_preserves_its_matcher_and_does_not_invent_arguments():
    result = prepared("""import {test} from 'vitest';
test('callback', () => {
    register((value) => {
        expect(() => value.parse()).not.toThrow();
    });
});
""", 'typescript')
    assert result['status'] == 'partial'
    checks = list(result['obligations'].values())
    assert len(checks) == 1
    assert source_text(result, checks[0]['predicate']) == 'expect(() => value.parse()).not.toThrow()'
    assert any(row['code'] == 'callback_invocation_binding_unproved' for row in result['unknowns'])
    assert any(parameter['name'] == 'value' for unit in result['units'].values() for parameter in unit['parameters'])


def test_renderer_displays_predicate_guard_and_actual_formal_text_with_refs():
    result = prepared('''def check(values):
    if values:
        assert values[0] == 1
        check(values[1:])
def test_case():
    check([1, 2])
''')
    text = render(result)
    assert 'predicate="values[0] == 1"' in text
    assert 'if_statement "values" S' in text
    assert 'values <- "values[1:]" S' in text
    assert 'values <- "[1, 2]" S' in text
    assert len(result['calls']) == 2


def test_python_expected_exception_and_handler_are_readable_without_byte_lookup():
    result = prepared('''import pytest
def test_case():
    try:
        with pytest.raises(ValueError):
            parse('bad')
    except AssertionError:
        assert fallback == 1
''')
    text = render(result)
    assert 'expected="ValueError"' in text
    assert 'predicate="fallback == 1"' in text
    assert 'except_clause "except AssertionError:' in text
    assert 'matching_exception_adapter_exit' in text


def test_go_custom_failure_helper_renders_guard_and_each_call_binding():
    result = prepared('''package example
import "testing"
func reject(t *testing.T, message string) { t.Fatal(message) }
func inspect(t *testing.T, actual int, expected int) {
    if actual != expected { reject(t, "mismatch") }
}
func TestCase(t *testing.T) { inspect(t, 3, 4) }
''', 'go')
    text = render(result)
    assert 'predicate="actual != expected"' in text
    assert 'actual <- "3" S' in text
    assert 'expected <- "4" S' in text
    assert 'guard_false_on_normal_completion' in text
    assert len(result['units']) == 3


def test_fallback_never_promotes_production_expectation_spelling():
    result = prepared("""import {test} from 'vitest';
import {compute} from '../library';
test('result', () => { expect(compute(3)).toBe(4); });
""", 'typescript', extra={'library.ts': 'export function compute(n) { expect(PRODUCTION_SENTINEL).toBe(9); return n; }'})
    assert len(result['obligations']) == 1
    assert 'PRODUCTION_SENTINEL' not in render(result)


def test_large_go_type_switch_uses_direct_header_tokens_and_keeps_full_source():
    checks = '\n'.join(f'  if entry.Marker != {value} {{ t.Fatal("value {value}") }}' for value in range(18))
    code = '''package example
import "testing"
func leaf(t *testing.T, value int) { if value < 0 { t.Fatal("negative") } }
func inspect(t *testing.T, value interface{}) {
 switch entry := func() interface{} { return value }().(type) {
 // CONTROL_BODY_SENTINEL: this complete switch body belongs only in source.
 case struct{ Marker int }:
  // CASE_BODY_SENTINEL: never a case header or repeated control predicate.
''' + checks + '''
  leaf(t, entry.Marker)
 default:
  t.Fatal("wrong kind")
 }
}
func TestCase(t *testing.T) { inspect(t, struct{ Marker int }{Marker: 7}) }
'''
    result = prepared(code, 'go')
    assert result['status'] == 'complete'
    all_guards = [guard for row in [*result['obligations'].values(), *result['calls'].values()]
                  for guard in row['guards']]
    switches = [guard for guard in all_guards if guard['kind'] == 'type_switch_statement']
    cases = [guard for guard in all_guards if guard['kind'] == 'type_case']
    assert len(switches) >= 19 and cases
    assert {source_text(result, guard['header']) for guard in switches} == {
        'switch entry := func() interface{} { return value }().(type) '
    }
    assert {source_text(result, guard['header']) for guard in cases} == {'case struct{ Marker int }:'}
    assert all('CONTROL_BODY_SENTINEL' in source_text(result, guard['at']) for guard in switches)
    assert all('CASE_BODY_SENTINEL' in source_text(result, guard['at']) for guard in cases)
    snapshot = copy.deepcopy(result)
    output = render(result)
    assert result == snapshot
    assert output.count('CONTROL_BODY_SENTINEL') == 1
    assert output.count('CASE_BODY_SENTINEL') == 1
    assert 'type_switch_statement "switch entry := func() interface{} { return value }().(type) " S' in output
    assert 'type_case "case struct{ Marker int }:" S' in output
    assert '; control=S' in output
    assert len(result['obligations']) == 20
    assert list(result['obligations']) == ['Q' + str(index) for index in range(20)]


def test_unicode_source_excerpt_is_exact_and_explicit_about_omitted_characters():
    result = prepared('def test_case():\n    assert message == "猫🐈"\n')
    reference = result['units'][result['root']]['at']
    text = source_text(result, reference)
    excerpt = source_excerpt(result, reference, max_chars=len(text) - 2)
    assert excerpt == dict(ref=reference, text=text[:-2], omitted_chars=2)
    assert source_excerpt(result, reference, max_chars=0) == dict(ref=reference, text='', omitted_chars=len(text))
    assert source_excerpt(result, reference, max_chars=len(text))['omitted_chars'] == 0
    assert source_text(result, reference) == text
    with pytest.raises(ValueError):
        source_excerpt(result, reference, max_chars=-1)


def test_unknown_guard_display_is_bounded_with_exact_full_reference():
    code = 'UNKNOWN_CONTROL_BODY_' + '猫' * 400
    reference = dict(source='S0', start=0, end=len(code.encode()))
    document = dict(status='partial', sources={'S0': dict(path='unknown.py', start_byte=0,
                    end_byte=len(code.encode()), code=code)}, root='V0', obligations={
        'Q0': dict(unit='V0', kind='assert_expression', at=reference,
                   guards=[dict(kind='unknown_control', at=reference, branch='unknown')])})
    output = render(document)
    assert '[excerpt;' in output and 'chars omitted; full source S0[0:' in output
    assert '; header unavailable' in output
    # The full source survives, while its second appearance is explicitly bounded.
    assert output.count(code) == 1
    assert code in document['sources']['S0']['code']


def test_boundary_render_factors_common_fields_without_losing_order_or_facts():
    reference = dict(source='S0', start=0, end=4)
    boundaries = [
        dict(caller='V0', kind='unresolved', semantic_support='unconfirmed', source=reference),
        dict(caller='V1', kind='unresolved', semantic_support='unconfirmed', source=reference, extra='kept'),
        dict(caller='V1', kind='resolved', validation_provenance='unknown', source=reference,
             declaration_header=reference),
    ]
    document = dict(status='partial', sources={'S0': dict(path='tests/example.py', start_byte=0,
                    end_byte=4, code='call')}, root='V0', boundaries=boundaries)
    text = render(document).split('boundaries:\n', 1)[1]
    restored = []
    for line in text.splitlines():
        if line.startswith('shared '):
            common = json.loads(line.removeprefix('shared '))
        else:
            restored.append(common | json.loads(line))
    expected = [{key: 'S0[0:4]' if value == reference else value for key, value in row.items()}
                for row in boundaries]
    assert restored == expected
    assert text.count('"semantic_support":"unconfirmed"') == 1
