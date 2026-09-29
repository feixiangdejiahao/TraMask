"""Unlabelled miniature programs: selection rules frozen before pilot scoring."""
import copy
import inspect

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search.impact_selection import select


def fixture(language, code):
    path = {"python": "test_impact.py", "go": "impact_test.go", "typescript": "impact.test.ts"}[language]
    frontend = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend


def candidate(corpus, before, after, identifier, *, occurrence=0, role="input"):
    test_id = next(iter(corpus["tests"]))
    extent = corpus["tests"][test_id]["span"]
    data = corpus["sources"][extent["path"]]["code"].encode()
    start = extent["start_byte"]
    for _ in range(occurrence + 1):
        start = data.index(before.encode(), start)
        if _ < occurrence:
            start += len(before.encode())
    return dict(id=identifier, base_test_id=test_id, operator="input_change", imports=[], source_test_ids=[],
                edits=[dict(span=dict(path=extent["path"], start_byte=start, end_byte=start+len(before.encode())),
                            before=before, after=after, role=role)])


PROGRAMS = [
    ("python", """def transform(value): return value*2
def test_case():
    data = 11
    ignored = 23
    result = transform(data)
    assert result == 22
"""),
    ("go", """package sample
import "testing"
func transform(value int) int { return value*2 }
func TestCase(t *testing.T) {
    data := 11
    ignored := 23
    result := transform(data)
    if result != 22 { t.Fatal(result) }
}
"""),
    ("typescript", """function transform(value: number) { return value*2; }
test('case', () => {
    const data = 11;
    const ignored = 23;
    const result = transform(data);
    expect(result).toBe(22);
});
"""),
]


@pytest.mark.parametrize("language,code", PROGRAMS)
def test_actual_input_has_impact_and_unrelated_setup_does_not(language, code):
    corpus, frontend = fixture(language, code)
    active = candidate(corpus, "11", "19", "active")
    unrelated = candidate(corpus, "23", "31", "unrelated")
    result = select(corpus, frontend, [unrelated, active], budget=1)
    assert [row["id"] for row in result["selected"]] == ["active"]
    evidence = result["ranking"][0]["evidence"]
    assert len(evidence["obligations"]) == 1
    obligation = evidence["obligations"][0]
    assert obligation["observed"] == "result" and obligation["expected"] == "22"
    assert obligation["path"][0]["text"] == "11"
    assert obligation["path"][-1]["text"] == "result"
    assert obligation["actual_span"] and obligation["expected_span"]
    assert len(obligation["edge_kinds"]) == len(obligation["path"])-1
    assert result["ranking"][1]["evidence"]["obligations"] == []


def test_overwritten_binding_does_not_reach_later_assertion():
    corpus, frontend = fixture("python", """def test_case():
    data = 11
    data = 23
    result = process(data)
    assert result == 46
""")
    overwritten = candidate(corpus, "11", "19", "old")
    active = candidate(corpus, "23", "31", "current")
    result = select(corpus, frontend, [overwritten, active], budget=1)
    assert result["selected"][0]["id"] == "current"
    assert result["ranking"][1]["evidence"]["obligations"] == []


def test_expected_value_dependency_is_paired_but_not_proved_correct():
    corpus, frontend = fixture("python", """def test_case():
    data = 11
    result = process(data)
    expected = data * 2
    assert result == expected
""")
    result = select(corpus, frontend, [candidate(corpus, "11", "19", "paired")])
    evidence = result["ranking"][0]["evidence"]
    assert evidence["balanced_observation_ids"]
    assert evidence["obligations"] == []
    assert result["selected_count"] == 1  # Still eligible; no oracle proof.


@pytest.mark.parametrize("language,code", PROGRAMS[1:])
def test_adapter_expected_local_binding_recovers_a_real_dependency(language, code):
    if language == "go":
        code = code.replace("if result != 22", "expected := data * 2\n    if result != expected")
    else:
        code = code.replace("expect(result).toBe(22)", "const expected = data * 2;\n    expect(result).toBe(expected)")
    corpus, frontend = fixture(language, code)
    row = select(corpus, frontend, [candidate(corpus, "11", "19", "paired")])["ranking"][0]
    assert row["evidence"]["balanced_observation_ids"]
    assert not row["evidence"]["obligations"]


@pytest.mark.parametrize("language,code", PROGRAMS[1:])
def test_unknown_expected_global_is_not_invented_as_input_independent(language, code):
    code = code.replace("!= 22", "!= GlobalExpected").replace(".toBe(22)", ".toBe(GlobalExpected)")
    corpus, frontend = fixture(language, code)
    row = select(corpus, frontend, [candidate(corpus, "11", "19", "unknown")])["ranking"][0]
    assert row["evidence"]["eligible"]
    assert not row["evidence"]["obligations"]
    assert any(reason.startswith("expression_root_unresolved:") for reason in row["evidence"]["unknowns"])


def test_control_dependency_does_not_make_literal_expectation_adapt():
    corpus, frontend = fixture("python", """def test_case():
    data = 11
    if data > 0:
        result = process()
        assert result == 22
""")
    result = select(corpus, frontend, [candidate(corpus, "11", "-1", "control")])
    evidence = result["ranking"][0]["evidence"]
    assert evidence["obligations"]
    assert "control" in evidence["obligations"][0]["edge_kinds"]
    assert not evidence["balanced_observation_ids"]


def test_state_operation_keeps_may_effect_path_and_observation_phase():
    corpus, frontend = fixture("python", """def test_case():
    box = Box()
    assert box.value == 0
    box.push(11)
    assert box.value == 11
""")
    row = select(corpus, frontend, [candidate(corpus, "11", "19", "state")])["ranking"][0]
    assert len(row["evidence"]["obligations"]) == 1
    obligation = row["evidence"]["obligations"][0]
    assert "may_effect" in obligation["edge_kinds"]
    assert obligation["expected"] == "11"
    synthetic = next(node for node in obligation["path"] if node["kind"] == "may_effect")
    assert synthetic["text"] == "box.push(11)"
    assert synthetic["graph_label"] == "box"
    assert synthetic["text_basis"] == "complete_original_source_span"


def test_long_path_source_is_not_replaced_by_truncated_flow_label():
    value = "x" * 1000
    corpus, frontend = fixture("python", "def test_case():\n    result = process("+repr(value)+")\n    assert result == 1\n")
    row = select(corpus, frontend, [candidate(corpus, repr(value), repr("changed"), "long")])["ranking"][0]
    path = row["evidence"]["obligations"][0]["path"]
    literal = path[0]
    assert literal["text"] == repr(value)
    assert len(literal["graph_label"]) < len(literal["text"])
    for node in path:
        data = corpus["sources"][node["path"]]["code"].encode()
        assert node["text"] == data[node["start_byte"]:node["end_byte"]].decode()


def test_same_port_value_variants_do_not_consume_all_coverage_slots():
    corpus, frontend = fixture("python", """def test_case():
    first = process(11)
    assert first == 22
    second = process(23)
    assert second == 46
""")
    repeated = [candidate(corpus, "11", str(30+i), "variant_"+str(i)) for i in range(12)]
    other = candidate(corpus, "23", "39", "other_observation")
    result = select(corpus, frontend, repeated + [other], budget=2)
    assert "other_observation" in {row["id"] for row in result["selected"]}
    assert [row["new_observation_count"] for row in result["ranking"][:2]] == [1, 1]


def test_external_effect_without_local_binding_remains_unknown_exploration():
    corpus, frontend = fixture("python", """def test_case():
    configure("old")
    result = run()
    assert result == 0
""")
    row = select(corpus, frontend, [candidate(corpus, '"old"', '"new"', "opaque")])["ranking"][0]
    assert row["evidence"]["eligible"]
    assert row["evidence"]["obligations"] == []
    assert row["selected"]


def test_exploration_reserves_every_fourth_position_for_original_shape_order():
    corpus, frontend = fixture("python", """def test_case():
    ignored = 71
    a = process(11)
    b = process(23)
    c = process(37)
    d = process(41)
    assert a == 22
    assert b == 46
    assert c == 74
    assert d == 82
""")
    candidates = [candidate(corpus, value, "99", value) for value in ["11", "23", "37", "41", "71"]]
    result = select(corpus, frontend, candidates)
    selected_before = {row["id"] for row in result["ranking"][:3]}
    next_baseline = min((row for row in result["ranking"] if row["id"] not in selected_before),
                        key=lambda row: row["baseline_rank"])
    assert result["ranking"][3]["id"] == next_baseline["id"]
    assert result["ranking"][3]["selection_reason"] == "shape_exploration"


def test_noop_and_expected_only_edits_do_not_create_input_obligations():
    corpus, frontend = fixture(*PROGRAMS[0])
    noop = candidate(corpus, "11", "11", "noop")
    expected = candidate(corpus, "22", "38", "expectation", role="semantic_expected")
    result = select(corpus, frontend, [noop, expected])
    assert all(not row["evidence"]["obligations"] for row in result["ranking"])
    assert next(row for row in result["ranking"] if row["id"] == "expectation")["evidence"]["eligible"] is False


def test_complete_ranking_is_budget_and_input_order_independent_and_immutable():
    corpus, frontend = fixture(*PROGRAMS[0])
    candidates = [candidate(corpus, "11", str(100+i), str(i)) for i in range(8)]
    original = copy.deepcopy((corpus, frontend, candidates))
    zero = select(corpus, frontend, candidates, budget=0)
    three = select(corpus, frontend, list(reversed(candidates)), budget=3)
    assert [row["id"] for row in zero["ranking"]] == [row["id"] for row in three["ranking"]]
    assert zero["selected"] == [] and three["selected_count"] == 3
    assert len(three["ranking"]) == 8
    assert (corpus, frontend, candidates) == original


def test_runtime_instrumentation_cannot_change_priority_or_consume_assertion_slots():
    from relation_search.instrument import instrument_candidates
    corpus, frontend = fixture(*PROGRAMS[0])
    item = candidate(corpus, "11", "19", "instrumented")
    code = corpus["sources"]["test_impact.py"]["code"]
    before = "assert result == 22"
    start = code.index(before)
    item["runtime_probes"] = [dict(phase="before_assertion", insert_before=dict(
        path="test_impact.py", start_byte=start, end_byte=start+len(before)),
        roles=[dict(name="observed", expression="result")])]
    instrumented = next(row for row in instrument_candidates(corpus, [item])["candidates"]
                        if row["id"] == item["id"])
    assert instrumented["instrumentation"]["status"] == "instrumented"
    original_result = select(corpus, frontend, [item])
    instrumented_result = select(corpus, frontend, [instrumented])
    assert original_result["ranking"] == instrumented_result["ranking"]
    assert instrumented_result["selected"][0] is instrumented


def test_labels_caches_and_runtime_metadata_cannot_affect_evidence_or_ranks():
    corpus, frontend = fixture(*PROGRAMS[0])
    candidates = [candidate(corpus, "11", str(100+i), str(i)) for i in range(8)]
    annotated = copy.deepcopy(candidates)
    for i, row in enumerate(annotated):
        row.update(evaluation={"target": i == 7}, oracle_cache={"hit": i % 2 == 0},
                   runtime_outcome="fail" if i == 7 else "pass", case_name="special_case")
    assert select(corpus, frontend, candidates)["ranking"] == select(corpus, frontend, annotated)["ranking"]
    assert tuple(inspect.signature(select).parameters) == ("corpus", "frontend", "candidates", "budget")


def test_bad_source_edit_and_unknown_owner_are_explicit():
    corpus, frontend = fixture(*PROGRAMS[0])
    broken = candidate(corpus, "11", "99", "bad_edit")
    broken["edits"][0]["before"] = "different"
    result = select(corpus, frontend, [broken])
    assert result["selected"] == []
    assert "edit_source_mismatch" in result["ranking"][0]["evidence"]["unknowns"]
    renamed = copy.deepcopy(corpus)
    old_id = next(iter(renamed["tests"]))
    renamed["tests"]["unresolved_id"] = renamed["tests"].pop(old_id)
    unknown = candidate(corpus, "11", "99", "unknown_owner")
    unknown["base_test_id"] = "unresolved_id"
    unknown_frontend = copy.deepcopy(frontend)
    for row in unknown_frontend["observations"]:
        row["test_id"] = "unresolved_id"
    result = select(renamed, unknown_frontend, [unknown])
    assert result["selected_count"] == 1
    assert result["ranking"][0]["evidence"]["unknowns"] == ["local_flow_owner_unresolved"]


def test_empty_duplicate_and_invalid_budget():
    corpus, frontend = fixture(*PROGRAMS[0])
    item = candidate(corpus, "11", "99", "one")
    assert select(corpus, frontend, [])["ranking"] == []
    with pytest.raises(ValueError):
        select(corpus, frontend, [item, item])
    for budget in [-1, 1.5, True]:
        with pytest.raises(ValueError):
            select(corpus, frontend, [item], budget=budget)
