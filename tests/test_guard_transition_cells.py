"""Source-only toys distinguish numeric direction from observed guard cells."""
import copy

import pytest

from anchor_retrieval.syntax import Source
from prototypes.guard_transition_cells import candidate_cells
from prototypes.numeric_relation_buckets import candidate_relations
from relational_gap.frontend import extract_frontend, to_emitter_corpus


PROGRAMS = {
    "python": """def produce(value):
    return value + 2
def accept(available, cost):
    remaining = available - cost
    if remaining < 0:
        return False
    return True
def test_case():
    available = produce(3)
    cost = 7
    result = accept(available, cost)
    assert result is False
""",
    "go": """package demo
import "testing"
func produce(value int) int { return value + 2 }
func accept(available int, cost int) bool {
    remaining := available - cost
    if remaining < 0 { return false }
    return true
}
func TestCase(t *testing.T) {
    available := produce(3)
    cost := 7
    result := accept(available, cost)
    if result != false { t.Fatal(result) }
}
""",
    "typescript": """function produce(value: number) { return value + 2; }
function accept(available: number, cost: number) {
    const remaining = available - cost;
    if (remaining < 0) { return false; }
    return true;
}
test('case', () => {
    const available = produce(3);
    const cost = 7;
    const result = accept(available, cost);
    expect(result).toBe(false);
});
""",
}


def fixture(language="python", code=None):
    code = code or PROGRAMS[language]
    path = {"python": "test_guard.py", "go": "guard_test.go", "typescript": "guard.test.ts"}[language]
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend


def change(corpus, before, after, name="candidate"):
    test_id = next(iter(corpus["tests"]))
    extent = corpus["tests"][test_id]["span"]
    data = corpus["sources"][extent["path"]]["code"].encode()
    start = data.index(before.encode(), extent["start_byte"])
    return dict(id=name, base_test_id=test_id, imports=[], source_test_ids=[], edits=[dict(
        span=dict(path=extent["path"], start_byte=start, end_byte=start+len(before.encode())),
        before=before, after=after, role="input")])


@pytest.mark.parametrize("language", PROGRAMS)
def test_same_edit_direction_splits_when_producer_output_crosses_consumers_guard(language):
    corpus, frontend = fixture(language)
    below = change(corpus, "3", "4", "below")
    above = change(corpus, "3", "6", "above")
    old_below = candidate_relations(corpus, below)
    old_above = candidate_relations(corpus, above)
    assert old_below[0]["delta_order"] == old_above[0]["delta_order"] == 1
    assert old_below[0]["context"] == old_above[0]["context"] == []
    first, second = candidate_cells(corpus, frontend, below), candidate_cells(corpus, frontend, above)
    assert first["records"] and second["records"], (first, second)
    assert first["cell_id"] != second["cell_id"]
    a, b = first["records"][0], second["records"][0]
    assert a["before_operands"] == b["before_operands"] == [-2, 0]
    assert a["after_operands"] == [-1, 0] and b["after_operands"] == [1, 0]
    assert a["before_order"] == b["before_order"] == -1
    assert a["after_order"] == -1 and b["after_order"] == 1
    assert b["actual_formal_chain"][-1]["after_arguments"] == {"available": 8, "cost": 7}
    assert b["observation_ids"]
    assert not first["observation_equivalence_proved"]


def test_same_guard_cell_does_not_claim_same_output_or_delete_candidates():
    corpus, frontend = fixture()
    a = candidate_cells(corpus, frontend, change(corpus, "3", "6", "first"))
    b = candidate_cells(corpus, frontend, change(corpus, "3", "9", "second"))
    assert a["cell_id"] == b["cell_id"]
    assert a["records"][0]["after_operands"] != b["records"][0]["after_operands"]
    assert not a["observation_equivalence_proved"] and not a["execution_or_oracle_inference"]


def test_joint_edit_uses_the_other_operations_new_input():
    corpus, frontend = fixture()
    item = change(corpus, "3", "6")
    item["edits"].extend(change(corpus, "7", "9")["edits"])
    result = candidate_cells(corpus, frontend, item)
    assert result["records"][0]["after_operands"] == [-1, 0]
    assert result["records"][0]["after_order"] == -1


def test_unused_function_guard_does_not_enter_an_observation_cell():
    corpus, frontend = fixture(code="def unrelated(value):\n    if value > 100: return 1\n    return 0\n"+PROGRAMS["python"])
    result = candidate_cells(corpus, frontend, change(corpus, "3", "6"))
    assert len(result["records"]) == 1
    assert result["records"][0]["operator"] == "<"


def test_actual_formal_transport_reaches_guard_inside_a_forwarding_helper():
    code = PROGRAMS["python"].replace("def test_case():", "def forward(left, right):\n    return accept(left, right)\ndef test_case():")
    code = code.replace("result = accept(available, cost)", "result = forward(available, cost)")
    corpus, frontend = fixture(code=code)
    result = candidate_cells(corpus, frontend, change(corpus, "3", "6"))
    assert len(result["records"]) == 1
    record = result["records"][0]
    assert len(record["actual_formal_chain"]) == 2
    assert record["after_operands"] == [1, 0]
    assert record["actual_formal_chain"][0]["after_arguments"] == {"left": 8, "right": 7}
    assert record["actual_formal_chain"][1]["after_arguments"] == {"available": 8, "cost": 7}


def test_name_changes_do_not_change_the_numeric_relation_decision():
    results = []
    for code in [PROGRAMS["python"], PROGRAMS["python"].replace("available", "supply").replace("cost", "demand")]:
        corpus, frontend = fixture(code=code)
        record = candidate_cells(corpus, frontend, change(corpus, "3", "6"))["records"][0]
        results.append((record["before_order"], record["after_order"], record["before_operands"], record["after_operands"]))
    assert results[0] == results[1]


def test_rebinding_before_consumer_stops_the_changed_value():
    code = PROGRAMS["python"].replace("    cost = 7", "    available = 5\n    cost = 7")
    corpus, frontend = fixture(code=code)
    result = candidate_cells(corpus, frontend, change(corpus, "3", "6"))
    assert result["records"] == [] and result["cell_id"] is None


def test_unmodelled_augmented_assignment_is_not_treated_as_an_ordinary_definition():
    code = PROGRAMS["python"].replace("    cost = 7", "    available += 2\n    cost = 7")
    corpus, frontend = fixture(code=code)
    result = candidate_cells(corpus, frontend, change(corpus, "3", "6"))
    assert result["records"] == []
    assert any(row["reason"] == "augmented_assignment_not_in_scalar_fragment" for row in result["unknowns"])


def test_common_scalar_fragment_does_not_assume_go_narrow_integer_semantics():
    code = PROGRAMS["go"].replace("value int", "value int8")
    corpus, frontend = fixture("go", code)
    result = candidate_cells(corpus, frontend, change(corpus, "3", "6"))
    assert not result["records"]
    assert any(row["reason"] == "go_integer_type_not_in_common_fragment" for row in result["unknowns"])


@pytest.mark.parametrize("producer", [
    "def produce(value):\n    if value > 4: return value\n    return 5\n",
    "def produce(value):\n    emit(value)\n    return value + 2\n",
    "def produce(value):\n    def callback(): return value\n    return callback()\n",
])
def test_effectful_branching_or_closure_helper_is_unknown(producer):
    code = producer+"def accept"+PROGRAMS["python"].split("def accept", 1)[1]
    corpus, frontend = fixture(code=code)
    result = candidate_cells(corpus, frontend, change(corpus, "3", "6"))
    # A producer's own guard can still be a valid cell. Its unknown return
    # value must not be invented to instantiate the later consumer's guard.
    functions = {row["id"]: row for row in frontend["functions"]}
    assert not any(functions[row["function_id"]]["name"] == "accept" for row in result["records"])
    assert result["unknowns"]


def test_embedded_constraint_is_not_interpreted_as_a_host_language_guard():
    corpus, frontend = fixture(code='''def test_case():
    rule = "input < 7"
    result = engine(rule, 3)
    assert result is False
''')
    result = candidate_cells(corpus, frontend, change(corpus, "3", "6"))
    assert result["cell_id"] is None and result["unknowns"]


def test_replacement_callee_never_reuses_original_formal_bindings():
    corpus, frontend = fixture()
    result = candidate_cells(corpus, frontend, change(corpus, "accept", "other"))
    assert not result["records"]
    assert any(row["reason"] == "modified_callee_binding" for row in result["unknowns"])


def test_added_import_shadowing_original_callable_does_not_reuse_old_source():
    corpus, frontend = fixture()
    item = change(corpus, "3", "6")
    item["imports"] = [dict(name="accept", module="elsewhere", imported_name="accept")]
    result = candidate_cells(corpus, frontend, item)
    assert not result["records"]
    assert any(row["reason"] == "added_import_binding_not_reanalysed" for row in result["unknowns"])


def test_labels_and_cache_do_not_change_program_relations():
    corpus, frontend = fixture()
    item = change(corpus, "3", "6")
    annotated = copy.deepcopy(item)
    annotated.update(evaluation={"target": True}, oracle_cache={"hit": True}, case="special", outcome="fail")
    assert candidate_cells(corpus, frontend, item) == candidate_cells(corpus, frontend, annotated)
