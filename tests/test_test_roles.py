"""Independent role/contract fixtures; no pilot case or subject API rules."""
import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relation_search.test_roles import analyze
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture(code, language="python", edits=(), **kwargs):
    path = {"python": "test_roles.py", "go": "roles_test.go", "typescript": "roles.test.ts"}[language]
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    candidate = {"id": "candidate", "base_test_id": next(iter(corpus["tests"])), "edits": []}
    for before, after, role in edits:
        owner = corpus["tests"][candidate["base_test_id"]]["span"]
        begin = code.encode().index(before.encode(), owner["start_byte"])
        candidate["edits"].append({"span": {"path": path, "start_byte": begin, "end_byte": begin + len(before.encode())}, "before": before, "after": after, "role": role})
    frozen = copy.deepcopy((corpus, frontend, candidate))
    result = analyze(corpus, frontend, candidate, **kwargs)
    assert (corpus, frontend, candidate) == frozen
    json.dumps(result)
    return result


def codes(result):
    return {row["code"] for row in result["findings"]}


@pytest.mark.parametrize("assertion", ["len(subject()) == []", "[] == len(subject())", "len(subject()) == {}", "len(subject()) == 'x'"])
def test_builtin_length_cannot_equal_builtin_container_or_string(assertion):
    result = fixture(f"def test_example():\n    assert {assertion}\n")
    assert result["status"] == "invalid"
    assert codes(result) == {"equality_type_contradiction"}
    assert result["findings"][0]["provenance"]


def test_observation_replacement_is_checked_after_reparsing():
    code = "def test_example():\n    assert list(subject()) == []\n"
    result = fixture(code, edits=[("list(subject())", "len(list(subject()))", "input")])
    assert result["status"] == "invalid"
    assert result["changes"][0]["after"] == "len(list(subject()))"


def test_type_follows_unique_prior_alias_without_using_variable_names():
    result = fixture("def test_example():\n    x = len(subject())\n    y = x\n    z = []\n    assert y == z\n")
    assert "equality_type_contradiction" in codes(result)


@pytest.mark.parametrize("code", [
    "def test_example(len):\n    assert len(subject()) == []\n",
    "def test_example():\n    len = maker()\n    assert len(subject()) == []\n",
    "len = maker()\ndef test_example():\n    assert len(subject()) == []\n",
    "def len(x):\n    return []\ndef test_example():\n    assert len(subject()) == []\n",
    "def test_example():\n    x = 1\n    if flag:\n        x = []\n    assert x == []\n",
    "def test_example():\n    x = 1\n    x = []\n    assert x == []\n",
])
def test_shadowed_builtin_or_ambiguous_definition_does_not_prove_contradiction(code):
    assert "equality_type_contradiction" not in codes(fixture(code))


@pytest.mark.parametrize("assertion", ["True == 1", "False == 0.0", "len(subject()) != []", "custom() == []"])
def test_numeric_bool_inequality_and_opaque_equality_are_not_rejected(assertion):
    assert fixture(f"def test_example():\n    assert {assertion}\n")["status"] != "invalid"


def test_expected_literal_change_alone_is_not_a_new_combination():
    result = fixture("def test_example():\n    assert subject() == '界'\n", edits=[("'界'", "'other'", "input")])
    assert codes(result) == {"expected_only_program_edit"}
    assert result["status"] == "review"
    extent = result["findings"][0]["span"]
    assert extent["end_byte"] - extent["start_byte"] == len("'other'".encode())


def test_joint_input_expected_edit_is_reviewable_and_semantic_expected_is_allowed():
    code = "def test_example():\n    assert subject(1) == 'old'\n"
    result = fixture(code, edits=[("subject(1)", "subject(2)", "input"), ("'old'", "'new'", "input")])
    assert result["status"] == "review"
    assert codes(result) == {"expected_construction_edited"}
    result = fixture(code, edits=[("'old'", "'new'", "semantic_expected")])
    assert "expected_only_program_edit" not in codes(result)


def test_expected_alias_role_propagates_to_its_literal_definition():
    code = "def test_example():\n    z = 'old'\n    alias = z\n    assert subject() == alias\n"
    result = fixture(code, edits=[("'old'", "'new'", "input")])
    assert "expected_only_program_edit" in codes(result)
    assert any(row["role"] == "expected" and row["span"]["start_byte"] == code.index("'old'") for row in result["roles"])


@pytest.mark.parametrize("name,parameters,invocation", [
    ("arbitrary", "a, b", "arbitrary(subject(), 'old')"),
    ("compare", "b, a", "compare('old', subject())"),
    ("not_an_assert_name", "a, b", "not_an_assert_name(b='old', a=subject())"),
])
def test_helper_role_follows_binding_not_helper_name_or_argument_position(name, parameters, invocation):
    code = f"def {name}({parameters}):\n    assert a == b\ndef test_example():\n    {invocation}\n"
    result = fixture(code, edits=[("'old'", "'new'", "input")])
    assert "expected_only_program_edit" in codes(result)
    assert result["findings"][0]["provenance"][0]["provenance"][0]["call_path"]


def test_python_callback_return_is_expected_value_not_test_input():
    code = "def compare(a, b):\n    observed = subject(a)\n    expected = b()\n    assert observed == expected\ndef test_example():\n    compare('input', lambda: {'x': 7})\n"
    result = fixture(code, edits=[("7", "8", "input")])
    assert "expected_only_program_edit" in codes(result)
    assert any(step["kind"] == "source_resolved_return" for row in result["roles"] for step in row["provenance"])


def test_expected_callback_closure_follows_outer_alias():
    code = "def compare(a, b):\n    assert subject(a) == b()\ndef test_example():\n    z = 'old'\n    compare(1, lambda: z)\n"
    assert "expected_only_program_edit" in codes(fixture(code, edits=[("'old'", "'new'", "input")]))


def test_expected_constructor_callback_is_reviewed_without_assuming_call_purity():
    code = "def compare(a, b):\n    assert subject(a) == b()\ndef test_example():\n    compare(1, lambda: build(7))\n"
    result = fixture(code, edits=[("7", "8", "input")])
    assert result["status"] == "review"
    assert "ambiguous_oracle_role" in codes(result)
    assert any(row["code"] == "opaque_value_call" for row in result["unknowns"])


def test_shared_actual_expected_definition_requires_review():
    code = "def test_example():\n    x = 1\n    assert x == x\n"
    result = fixture(code, edits=[("1", "2", "input")])
    assert result["status"] == "review"
    assert codes(result) == {"ambiguous_oracle_role"}


def test_input_to_opaque_actual_call_also_used_as_expected_is_not_oracle_only():
    code = "def test_example():\n    x = 1\n    assert compute(x) == x\n"
    result = fixture(code, edits=[("1", "2", "input")])
    assert result["status"] == "review"
    assert codes(result) == {"shared_actual_expected_dependency_edited"}


def test_opaque_expected_call_argument_does_not_inherit_proved_purity():
    code = "def test_example():\n    assert subject() == compute(7)\n"
    result = fixture(code, edits=[("7", "8", "input")])
    assert result["status"] == "review"
    assert "ambiguous_oracle_role" in codes(result)


@pytest.mark.parametrize("action", ["consume(x)", "resource.update(x)"])
def test_expected_alias_also_consumed_by_standalone_action_is_reviewable(action):
    code = f"def test_example():\n    x = 'old'\n    {action}\n    assert subject() == x\n"
    result = fixture(code, edits=[("'old'", "'new'", "input")])
    assert result["status"] == "review"
    assert codes(result) == {"expected_construction_edited"}


def test_helper_expected_formal_consumed_by_other_action_is_not_proved_oracle_only():
    code = "def compare(a, b):\n    consume(b)\n    assert a == b\ndef test_example():\n    compare(subject(), 'old')\n"
    result = fixture(code, edits=[("'old'", "'new'", "input")])
    assert result["status"] == "review"
    assert codes(result) == {"expected_construction_edited"}


@pytest.mark.parametrize("helper", [
    "def producer():\n    if flag:\n        return 1\n",
    "async def producer():\n    return 1\n",
    "@transform\ndef producer():\n    return 1\n",
    "def producer():\n    yield 1\n    return 2\n",
])
def test_partial_async_decorated_and_generator_return_are_not_number_proofs(helper):
    code = helper + "def test_example():\n    assert producer() == None\n"
    assert "equality_type_contradiction" not in codes(fixture(code))


def test_production_body_returning_wrong_type_is_not_a_test_contradiction():
    # The contract may require a list, and returning 3 may be the real bug.
    code = "def producer():\n    return 3\ndef test_example():\n    assert producer() == []\n"
    assert "equality_type_contradiction" not in codes(fixture(code))


def test_expected_only_edit_may_strengthen_a_weak_oracle():
    code = "def producer():\n    return 0\ndef test_example():\n    assert producer() == 0\n"
    result = fixture(code, edits=[("0", "1", "input")])
    assert result["status"] == "review"
    assert codes(result) == {"expected_only_program_edit"}


def test_explicit_module_rebinding_does_not_use_old_helper_body():
    code = "def compare(a, b):\n    assert a == b\ncompare = external()\ndef test_example():\n    compare(subject(), 'old')\n"
    result = fixture(code, edits=[("'old'", "'new'", "input")])
    assert not result["findings"]
    assert result["assertion_count"] == 0
    assert any(row["code"] == "source_callee_binding_modified" for row in result["unknowns"])


def test_explicit_standard_node_assert_method_write_removes_primitive_proof():
    code = '''import check from "node:assert/strict";
import { test } from "vitest";
check.strictEqual = fake;
test("example", () => { check.strictEqual(1, []); });
'''
    assert fixture(code, "typescript")["status"] == "unknown"


def test_typescript_alias_and_negated_matcher_preserve_framework_meaning():
    code = '''import { expect as check, test } from "vitest";
test("example", () => { check(1).not.toEqual([]); });
'''
    result = fixture(code, "typescript")
    assert result["assertion_count"] == 1
    assert "equality_type_contradiction" not in codes(result)


def test_go_expected_builder_crosses_formal_callback_return_boundary():
    code = '''package sample
import "testing"
import check "github.com/stretchr/testify/require"
type Pair struct { X int }
func checkOutput(t *testing.T, input string, f func() Pair) {
    actual := produce(input)
    desired := f()
    check.Equal(t, desired, actual)
}
func TestExample(t *testing.T) {
    checkOutput(t, "input", func() Pair { return Pair{X: 7} })
}
'''
    result = fixture(code, "go", [("7", "8", "input")])
    assert result["status"] == "review", result
    assert "expected_only_program_edit" in codes(result)


def test_go_grouped_parameters_keep_each_actual_formal_binding():
    code = '''package p
import "testing"
func compare(t *testing.T, a, b string) { if a != b { t.Error("bad") } }
func TestExample(t *testing.T) { compare(t, read(), "old") }
'''
    assert "expected_only_program_edit" in codes(fixture(code, "go", [("\"old\"", "\"new\"", "input")]))


def test_go_renamed_require_alias_and_opaque_position_builder_are_reviewable():
    code = '''package p
import "testing"
import eq "github.com/stretchr/testify/require"
type Pair struct { X int }
func compare(t *testing.T, f func(func(int) int) Pair, input string) {
    actual := produce(input)
    wanted := f(func(x int) int { return position(x) })
    eq.Equal(t, wanted, actual)
}
func TestExample(t *testing.T) { compare(t, func(p func(int) int) Pair { return Pair{X:p(7)} }, "input") }
'''
    result = fixture(code, "go", [("7", "8", "input")])
    assert "expected_construction_edited" in codes(result), result
    assert result["status"] == "review"


def test_nonstandard_same_spelling_assertion_is_not_a_proved_role():
    code = '''package p
import "testing"
import require "example.org/custom"
func TestExample(t *testing.T) { require.Equal(t, "old", read()) }
'''
    assert fixture(code, "go", [("\"old\"", "\"new\"", "input")])["status"] == "unknown"


def test_typescript_callback_returns_expected_object_with_imported_framework():
    code = '''import { expect, test } from "vitest";
function compare(x: string, y: () => object) {
  const observed = produce(x);
  expect(observed).toEqual(y());
}
test("example", () => { compare("input", () => ({field: 7})); });
'''
    result = fixture(code, "typescript", [("7", "8", "input")])
    assert "expected_only_program_edit" in codes(result), result


def test_typescript_standard_node_assert_type_contradiction():
    code = '''import assert from "node:assert/strict";
import { test } from "vitest";
test("example", () => { assert.strictEqual(1, []); });
'''
    assert fixture(code, "typescript")["status"] == "invalid"


def test_typescript_loose_equality_is_not_assumed_strict():
    code = '''import assert from "node:assert";
import { test } from "vitest";
test("example", () => { assert.equal(0, []); });
'''
    assert fixture(code, "typescript")["status"] != "invalid"


def test_call_budget_and_no_assertions_are_unknown_not_valid():
    code = "def compare(a, b):\n    assert a == b\ndef test_example():\n    compare(subject(), 'old')\n"
    result = fixture(code, max_contexts=1)
    assert result["status"] == "unknown"
    assert any(row["code"] == "call_context_budget_or_recursion" for row in result["unknowns"])
    assert fixture("def test_example():\n    run(1)\n")["status"] == "unknown"


def test_candidate_parse_error_retains_unknown_and_source_unchanged():
    result = fixture("def test_example():\n    assert subject() == 1\n", edits=[("1", "[", "input")])
    assert result["status"] == "unknown"
    assert result["unknowns"][0]["code"] == "modified_source_parse_error"


def test_source_variadic_failure_wrapper_traces_callback_without_assuming_operand_direction():
    code = '''package p
import "testing"
type Pair struct { X int }
func halt(z *testing.T, details ...interface{}) { trace(details); z.FailNow() }
func compare(t *testing.T, a, b interface{}, notes ...interface{}) {
  if a != b { halt(t, a, b, notes...) }
}
func run(t *testing.T, input string, f func() Pair) {
  observed := produce(input)
  desired := f()
  compare(t, observed, desired)
}
func TestExample(t *testing.T) { run(t, "input", func() Pair { return Pair{X:7} }) }
'''
    result = fixture(code, "go", [("7", "8", "input")])
    assert result["status"] == "review", result
    assert "ambiguous_oracle_role" in codes(result)
    assert result["guard_constraints"]
    assert result["argument_bindings"]
    assert any(row["basis"] == "symmetric_failure_operand_may" for row in result["roles"])


@pytest.mark.parametrize("prefix,suffix,kind", [
    ("if flag:\n        ", "", "if_statement"),
    ("with expecting_error():\n        trigger()\n        ", "", "with_statement"),
    ("try:\n        ", "\n    except ValueError:\n        pass", "try_statement"),
])
def test_guarded_or_exception_phase_contradiction_requires_applicability_review(prefix, suffix, kind):
    code = "def test_example():\n    " + prefix + "assert len(subject()) == []" + suffix + "\n"
    result = fixture(code)
    assert result["status"] == "review"
    row = result["assertions"][0]
    assert any(context["kind"] == kind for context in row["guard_contexts"])
    assert result["findings"][0]["applicability"] == "only_if_assertion_executes_normally"


def test_caller_expected_exception_context_reaches_helper_assertion():
    code = "def helper():\n    assert len(subject()) == []\ndef test_example():\n    with expecting_error():\n        helper()\n"
    result = fixture(code)
    assert result["status"] == "review"
    path = result["assertions"][0]["call_path"]
    assert path[0]["guard_contexts"][0]["kind"] == "with_statement"


def test_typescript_callback_selects_literal_fixture_without_subject_return_specification():
    code = '''import { expect, test } from "vitest";
function run(input: string, wanted: () => object, ...notes: unknown[]) {
  expect(produce(input)).toEqual(wanted());
}
test("example", () => { run("input", () => ({value: 7}), "diagnostic"); });
'''
    result = fixture(code, "typescript", [("7", "8", "input")])
    assert result["status"] == "review"
    assert "expected_only_program_edit" in codes(result)
    assert result["argument_bindings"]
