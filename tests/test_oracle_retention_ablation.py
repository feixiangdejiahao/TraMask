import copy

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.atomic_observations import AtomicBudget, atomize_candidates
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.oracle_retention_ablation import RetentionBudget, restore_source_observations


def fixture(code, language="python", path="test_retention.py", edit=None):
    data = extract_frontend([Source(path, code, language)])
    corpus = to_emitter_corpus(data)
    q = data["observations"][-1]
    edits = []
    if edit:
        before, after = edit
        start = code.encode().index(before.encode())
        edits = [{"before": before, "after": after,
                  "span": {"path": path, "start_byte": start, "end_byte": start + len(before.encode())}}]
    source = {"id": "source", "base_test_id": q["test_id"], "kind": "toy_input",
              "source_observation_id": q["id"], "edits": edits, "oracle": {"mode": "retain_all"}}
    atomic = atomize_candidates(corpus, data, [source], AtomicBudget())["candidates"][0]
    atomic["execution_lane"] = "source_q"
    return corpus, atomic


def test_absorbed_actual_edit_is_recovered_and_evaluated_once():
    code = '''events = []
def action(value):
    events.append(value)
    return value
def test_seed():
    events.clear()
    assert action(2) == 2
    assert len(events) == 1
'''
    corpus, atomic = fixture(code, edit=("action(2)", "action(4)"))
    saved = copy.deepcopy((corpus, atomic))
    result = restore_source_observations(corpus, [atomic])
    assert not result["unknowns"]
    restored = result["candidates"][0]
    assert restored["edits"] == atomic["atomic_observation"]["input_edits"]
    assert restored["ablation"]["recovered_absorbed_input_edits"]
    emitted = emit(corpus, [restored])
    assert not emitted["unsupported"]
    assert "assert action(4) == 2" in emitted["files"]["test_retention.py"]
    namespace = {}
    exec(emitted["files"]["test_retention.py"], namespace)
    with pytest.raises(AssertionError):
        namespace[emitted["obligations"][0]["test_name"]]()
    assert namespace["events"] == [4]
    assert (corpus, atomic) == saved


def test_unabsorbed_input_and_exception_guard_edits_remain_exact():
    corpus, atomic = fixture("def test_seed():\n    value = 2\n    assert value == 2\n    assert value > 0\n", edit=("value = 2", "value = 4"))
    atomic["edits"][0]["role"] = "source_exception_context"
    atomic["atomic_observation"]["input_edits"][0]["role"] = "source_exception_context"
    restored = restore_source_observations(corpus, [atomic])["candidates"][0]
    assert restored["edits"] == [atomic["edits"][0]]
    assert restored["oracle"]["mode"] == "retain_all"
    assert "source_observation_id" not in restored
    assert restored["static_parent_id"] == restored["id"]
    assert restored["ablation_parent_id"] == atomic["id"]


@pytest.mark.parametrize("language,path,code", [
    ("typescript", "retention.test.ts", 'test("seed", () => { expect(action(2)).toBe(2); expect(count).toBe(1); });'),
    ("go", "retention_test.go", 'package toy\nimport "testing"\nfunc TestSeed(t *testing.T) { if action(2) != 2 { t.Fatal("bad") }; if count != 1 { t.Fatal("count") } }'),
])
def test_language_neutralizations_restore_framework_checks(language, path, code):
    corpus, atomic = fixture(code, language, path)
    result = restore_source_observations(corpus, [atomic])
    assert not result["unknowns"]
    assert result["candidates"][0]["edits"] == []


def test_typescript_absorbed_argument_edit_and_utf8_offsets_are_preserved():
    corpus, atomic = fixture('// é\ntest("seed", () => { expect(action(2)).toBe(2); expect(count).toBe(1); });',
                             "typescript", "retention.test.ts", edit=("action(2)", "action(4)"))
    result = restore_source_observations(corpus, [atomic])
    assert not result["unknowns"]
    restored = result["candidates"][0]
    assert restored["edits"] == atomic["atomic_observation"]["input_edits"]
    emitted = emit(corpus, [restored])
    assert "expect(action(4)).toBe(2)" in emitted["files"]["retention.test.ts"]


@pytest.mark.parametrize("corruption", ["after", "before", "missing_input", "missing_observation"])
def test_corrupt_provenance_is_rejected(corruption):
    corpus, atomic = fixture("def test_seed():\n    assert action(2) == 2\n    assert count == 1\n", edit=("action(2)", "action(4)"))
    neutral = next(e for e in atomic["edits"] if e.get("role") == "atomic_neutralization")
    if corruption == "after": neutral["after"] = "not (action(99) == 2)"
    elif corruption == "before": neutral["before"] = "assert action(99) == 2"
    elif corruption == "missing_input": atomic["atomic_observation"].pop("input_edits")
    else: neutral["observation_id"] = "absent"
    result = restore_source_observations(corpus, [atomic])
    assert not result["candidates"] and result["unknowns"]


def test_semantic_lane_and_expected_edits_are_not_ablation_inputs():
    corpus, atomic = fixture("def test_seed():\n    assert a == 2\n    assert b == 1\n")
    llm = copy.deepcopy(atomic); llm["execution_lane"] = "llm_q"
    expected = copy.deepcopy(atomic); expected["edits"][0]["role"] = "semantic_expected"
    result = restore_source_observations(corpus, [llm, expected])
    assert not result["candidates"]
    assert len(result["unknowns"]) == 2


def test_whole_candidates_deduplicate_and_preserve_parent_links():
    corpus, atomic = fixture("def test_seed():\n    assert a == 2\n    assert b == 1\n")
    whole = copy.deepcopy(atomic); whole["id"] = "already_whole"; whole["edits"] = []
    whole.pop("atomic_observation")
    result = restore_source_observations(corpus, [whole, atomic])
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["ablation"]["original_candidate_ids"] == ["already_whole", atomic["id"]]


def test_original_finally_cleanup_executes_on_restored_assertion_failure():
    corpus, atomic = fixture('''events = []
def action(value):
    events.append(value)
    return value
def test_seed():
    events.clear()
    try:
        assert action(2) == 2
    finally:
        events.append("cleanup")
    assert events[-1] == "cleanup"
''', edit=("action(2)", "action(4)"))
    result = restore_source_observations(corpus, [atomic])
    emitted = emit(corpus, result["candidates"])
    namespace = {}; exec(emitted["files"]["test_retention.py"], namespace)
    with pytest.raises(AssertionError):
        namespace[emitted["obligations"][0]["test_name"]]()
    assert namespace["events"] == [4, "cleanup"]


def test_missing_unabsorbed_action_edit_is_rejected_instead_of_repaired():
    corpus, atomic = fixture("def test_seed():\n    value = 2\n    assert value == 2\n    assert value > 0\n", edit=("value = 2", "value = 4"))
    atomic["edits"] = [e for e in atomic["edits"] if e.get("role") == "atomic_neutralization"]
    result = restore_source_observations(corpus, [atomic])
    assert not result["candidates"]
    assert result["unknowns"][0]["reason"] == "original_input_or_guard_would_be_lost"


def test_budget_round_robin_is_per_base_and_inputs_are_bounded():
    data = extract_frontend([Source("test_budget.py", "def test_a():\n    assert 1\ndef test_b():\n    assert 1\n", "python")])
    corpus = to_emitter_corpus(data); a, b = list(corpus["tests"])
    candidates = [{"id": str(i), "base_test_id": base, "execution_lane": "source_q", "edits": [], "imports": [{"name": str(i)}]} for i, base in enumerate([a,a,a,b])]
    result = restore_source_observations(corpus, candidates, RetentionBudget(2))
    assert [c["base_test_id"] for c in result["candidates"]] == [a,b]
    assert result["counts"]["budget_exhausted"]
    assert restore_source_observations(corpus, candidates, RetentionBudget(2, 1))["counts"]["inspected"] == 1


@pytest.mark.parametrize("value", [0,129,True,1.5])
def test_budget_hard_cap(value):
    with pytest.raises(ValueError): RetentionBudget(value)
