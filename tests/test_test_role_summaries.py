"""Failure summaries follow source dispatch, not repository/helper names."""
import json

import pytest

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source, call_parts, child, walk
from relation_search.test_role_summaries import bind_fixed_prefix, failure_guard_constraints, summarize_failure_wrappers


def source_index(code, language="go"):
    path = {"go": "sample_test.go", "python": "test_sample.py", "typescript": "sample.test.ts"}[language]
    source = Source(path, code, language)
    assert not source.root.has_error
    return source, Index([source], "")


def binding(code, language="go", name="arbitrary"):
    source, index = source_index(code, language)
    unit = next(unit for unit in index.units.values() if unit.name == name)
    call = next(node for node in walk(source.root) if node.type in {"call", "call_expression"} and source.text(call_parts(node)[0]) == name)
    _, args = call_parts(call)
    return bind_fixed_prefix(unit, args, source), source


@pytest.mark.parametrize("tail", ["", ", 4, 5", ", notes..."])
def test_go_fixed_prefix_preserved_with_optional_or_expanded_variadic_diagnostics(tail):
    code = f'''package p
func arbitrary(a, b int, notes ...interface{{}}) {{}}
func TestExample() {{ arbitrary(1, 2{tail}) }}
'''
    result, source = binding(code)
    assert result["status"] == "fixed_prefix"
    assert [(row["parameter"], source.text(row["value_node"])) for row in result["bindings"]] == [("a", "1"), ("b", "2")]
    assert result["variadic_formals"] == ["notes"]
    if tail.endswith("..."):
        assert result["variadic_tail"][0]["status"] == "expanded_tail_unknown"


def test_spread_that_may_fill_fixed_formals_remains_unknown():
    result, _ = binding("package p\nfunc arbitrary(a, b int, rest ...int) {}\nfunc TestExample(){arbitrary(values...)}")
    assert result["status"] == "unknown" and not result["bindings"]


@pytest.mark.parametrize("signature,call", [
    ("a, b, *rest", "arbitrary(1, 2, 3)"),
    ("a, b=2, *rest", "arbitrary(1)"),
    ("a, *rest, b=2", "arbitrary(1, 3)"),
    ("a, *rest, b", "arbitrary(1, 3, b=2)"),
])
def test_python_fixed_parameters_defaults_and_keyword_only_formals(signature, call):
    result, source = binding(f"def arbitrary({signature}):\n    pass\ndef test_example():\n    {call}\n", "python")
    assert result["status"] == "fixed_prefix"
    assert [(row["parameter"], source.text(row["value_node"])) for row in result["bindings"]] == [("a", "1"), ("b", "2")]


def test_python_dynamic_kwargs_cannot_be_guessed_as_fixed_binding():
    result, _ = binding("def arbitrary(a, *rest):\n    pass\ndef test_example():\n    arbitrary(**data)\n", "python")
    assert result["status"] == "unknown" and not result["bindings"]


def test_typescript_rest_keeps_fixed_prefix_and_spread_tail_opaque():
    result, source = binding("function arbitrary(a: number, ...rest: unknown[]) {}\ntest('example', () => arbitrary(1, ...items));", "typescript")
    assert result["status"] == "fixed_prefix"
    assert [(row["parameter"], source.text(row["value_node"])) for row in result["bindings"]] == [("a", "1")]


@pytest.mark.parametrize("method", ["Error", "Errorf", "Fatal", "Fatalf", "Fail", "FailNow"])
def test_wrapper_discovered_from_declared_testing_receiver_without_helper_name_rule(method):
    code = f'''package p
import q "testing"
func entirelyRenamed(a int, x *q.T, diagnostics ...interface{{}}) {{
  format(a)
  x.{method}()
}}
'''
    _, index = source_index(code)
    summaries = summarize_failure_wrappers(index)
    assert len(summaries) == 1
    row = next(iter(summaries.values()))
    assert row["receiver"]["parameter"] == "x"
    assert row["receiver"]["parameter_index"] == 1
    assert row["sink"]["method"] == method
    json.dumps(summaries)


@pytest.mark.parametrize("code", [
    'package p\nimport q "other.org/testing"\nfunc wrapper(t *q.T){t.FailNow()}',
    'package p\nimport "testing"\nfunc wrapper(t *testing.T){if flag{return};t.FailNow()}',
    'package p\nimport "testing"\nfunc wrapper(t *testing.T){t=other();t.FailNow()}',
    'package p\nimport "testing"\nfunc wrapper(t *testing.T){defer t.FailNow()}',
    'package p\nimport "testing"\nfunc wrapper(t *testing.T){if flag{t.FailNow()}}',
])
def test_wrong_identity_early_return_rebinding_deferred_or_conditional_sink_not_summarized(code):
    _, index = source_index(code)
    assert not summarize_failure_wrappers(index)


def test_source_forwarding_wrappers_reach_fixpoint_without_named_api_rules():
    code = '''package p
import "testing"
func first(x *testing.T, args ...interface{}) { x.FailNow() }
func second(a int, y *testing.T, args ...interface{}) { first(y, args...) }
func third(z *testing.T) { second(1, z) }
'''
    _, index = source_index(code)
    summaries = summarize_failure_wrappers(index)
    assert {index.units[uid].name for uid in summaries} == {"first", "second", "third"}
    row = next(row for uid, row in summaries.items() if index.units[uid].name == "third")
    assert row["sink"]["kind"] == "source_failure_wrapper_forward"


def test_failure_guard_has_symmetric_operands_and_exact_source_provenance():
    code = '''package p
import "testing"
func abort(t *testing.T, args ...interface{}) { log(args); t.FailNow() }
func verify(t *testing.T, left, right interface{}, args ...interface{}) {
  if left != right { abort(t, left, right, args...) }
}
'''
    source, index = source_index(code)
    wrappers = summarize_failure_wrappers(index)
    unit = next(unit for unit in index.units.values() if unit.name == "verify")
    constraints = failure_guard_constraints(index, unit, wrappers)
    assert len(constraints) == 1
    row = constraints[0]
    assert row["role_precision"] == "symmetric_operands_no_oracle_direction"
    assert [source.text(node) for node in row["operand_nodes"]] == ["left", "right"]
    assert row["sink"]["kind"] == "source_failure_wrapper"
    assert "expected" not in row
    assert row["passing_relation"] == "=="


def test_guard_with_alternative_or_conditional_early_return_keeps_unknown():
    code = '''package p
import "testing"
func abort(t *testing.T) { t.FailNow() }
func verify(t *testing.T, a, b int) {
  if a != b { abort(t) } else { consume() }
  if a != b { if flag { return }; abort(t) }
}
'''
    _, index = source_index(code)
    unit = next(unit for unit in index.units.values() if unit.name == "verify")
    assert not failure_guard_constraints(index, unit, summarize_failure_wrappers(index))


def test_identically_named_dynamic_receiver_cannot_borrow_testing_dispatch():
    code = '''package p
import "testing"
type Fake struct{}
func verify(x *Fake, a, b int) { if a != b { x.FailNow() } }
'''
    _, index = source_index(code)
    unit = next(unit for unit in index.units.values() if unit.name == "verify")
    assert not failure_guard_constraints(index, unit, {})


def test_grouped_callable_formal_cannot_borrow_source_failure_wrapper():
    code = '''package p
import "testing"
func abort(t *testing.T) { t.FailNow() }
func verify(t *testing.T, ordinary, abort func(*testing.T), a, b int) {
  if a != b { abort(t) }
}
'''
    _, index = source_index(code)
    unit = next(unit for unit in index.units.values() if unit.name == "verify")
    assert not failure_guard_constraints(index, unit, summarize_failure_wrappers(index))
