"""Partial environments must forget unknown values without inventing them."""
import json

import pytest

from anchor_retrieval.syntax import Source
from experimental.guard_transition_cells import candidate_cells as strict_cells
from experimental.guard_transition_cells_v2 import candidate_cells
from relational_gap.frontend import extract_frontend, to_emitter_corpus


def fixture(language, *, object_input=False, depends_on_unknown=False, effectful=False):
    condition = "amount < context" if depends_on_unknown else "amount < 7"
    if language == "python":
        value = '{"value": 7}' if object_input else '"opaque"'
        if depends_on_unknown:
            value = "external()"
        helper = "    notify(context)\n" if effectful else ""
        code = f'''def produce(value, context):
{helper}    return value + 2
def accept(amount, context):
    if {condition}:
        return False
    return True
def test_case():
    context = {value}
    amount = produce(3, context)
    result = accept(amount, context)
    assert result is False
'''
        path = "test_partial.py"
    elif language == "go":
        value = 'map[string]int{"value": 7}' if object_input else '"opaque"'
        typ = "map[string]int" if object_input else "string"
        if depends_on_unknown:
            # An unknown dynamic integer is type correct for the negative.
            value, typ = "external()", "int"
        helper = "notify(context); " if effectful else ""
        code = f'''package sample
import "testing"
func produce(value int, context {typ}) int {{ {helper}return value + 2 }}
func accept(amount int, context {typ}) bool {{
    if {condition} {{ return false }}
    return true
}}
func TestCase(t *testing.T) {{
    context := {value}
    amount := produce(3, context)
    result := accept(amount, context)
    if result != false {{ t.Fatal(result) }}
}}
'''
        path = "partial_test.go"
    else:
        value = '{value: 7}' if object_input else '"opaque"'
        if depends_on_unknown:
            value = "external()"
        typ = "any"
        helper = "notify(context); " if effectful else ""
        code = f'''function produce(value: number, context: {typ}) {{ {helper}return value + 2; }}
function accept(amount: number, context: {typ}) {{
    if ({condition}) {{ return false; }}
    return true;
}}
test('case', () => {{
    const context = {value};
    const amount = produce(3, context);
    const result = accept(amount, context);
    expect(result).toBe(false);
}});
'''
        path = "partial.test.ts"
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    test_id = next(iter(corpus["tests"]))
    start = code.index("3", corpus["tests"][test_id]["span"]["start_byte"])
    candidate = dict(id="numeric_change", base_test_id=test_id, imports=[], source_test_ids=[], edits=[dict(
        before="3", after="6", role="input", span=dict(path=path, start_byte=start, end_byte=start+1))])
    return corpus, frontend, candidate


@pytest.mark.parametrize("language", ["python", "go", "typescript"])
@pytest.mark.parametrize("object_input", [False, True])
def test_unrelated_string_or_object_argument_does_not_hide_numeric_guard(language, object_input):
    corpus, frontend, candidate = fixture(language, object_input=object_input)
    baseline = strict_cells(corpus, frontend, candidate)
    result = candidate_cells(corpus, frontend, candidate)
    assert baseline["records"] == []
    assert len(result["records"]) == 1, result
    record = result["records"][0]
    assert record["before_operands"] == [5, 7] and record["after_operands"] == [8, 7]
    assert record["before_order"] == -1 and record["after_order"] == 1
    frame = record["actual_formal_chain"][-1]["after_arguments"]
    assert frame["context"]["abstract"] == "top" and frame["amount"] == 8
    assert result["partial_bindings"]
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("language", ["python", "go", "typescript"])
def test_guard_that_reads_unknown_parameter_stays_unknown(language):
    corpus, frontend, candidate = fixture(language, depends_on_unknown=True)
    result = candidate_cells(corpus, frontend, candidate)
    assert not result["records"] and result["cell_id"] is None
    assert result["unknowns"] and result["partial_bindings"]


@pytest.mark.parametrize("language", ["python", "go", "typescript"])
def test_unknown_parameter_does_not_make_an_effectful_producer_pure(language):
    corpus, frontend, candidate = fixture(language, object_input=True, effectful=True)
    result = candidate_cells(corpus, frontend, candidate)
    assert not result["records"]
    assert any(row["reason"] == "discarded_effectful_call" for row in result["partial_bindings"])


def test_changed_callee_is_not_rebound_by_allowing_unknown_arguments():
    corpus, frontend, candidate = fixture("python")
    extent = corpus["tests"][candidate["base_test_id"]]["span"]
    code = corpus["sources"][extent["path"]]["code"]
    start = code.index("accept(amount", extent["start_byte"])
    candidate["edits"].append(dict(before="accept", after="other", role="input",
        span=dict(path=extent["path"], start_byte=start, end_byte=start+len("accept"))))
    result = candidate_cells(corpus, frontend, candidate)
    assert not result["records"]
    assert any(row["reason"] == "modified_callee_binding" for row in result["unknowns"])
