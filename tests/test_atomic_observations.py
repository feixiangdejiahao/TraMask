import copy
import json

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.atomic_observations import AtomicBudget, atomize_candidates
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.semantics_v2 import prepare_requests


def fixture(code, language="python", path="test_atomic.py"):
    frontend = extract_frontend([Source(path, code, language)])
    return to_emitter_corpus(frontend), frontend


def candidate(data, q=None, edits=None):
    record = {"id": "input_change", "base_test_id": data["tests"][0]["id"], "source_test_ids": [],
              "kind": "source_argument_change", "edits": edits or [], "oracle": {"mode": "retain_all"}}
    if q:
        record["relation"] = {"source_observation_id": q["id"]}
    return record


def test_python_neutralization_preserves_changed_action_and_cleanup_and_whole_controls():
    corpus, data = fixture('''
events = []
class Resource:
    def __enter__(self):
        events.append("open")
    def __exit__(self, *args):
        events.append("closed")
def action(value):
    events.append(value)
    return value
def test_seed():
    events.clear()
    with Resource():
        assert action(2) == 2
        assert len(events) == 2
    assert events[-1] == "closed"
''')
    q = next(o for o in data["observations"] if o["observed"]["text"] == "len(events)")
    argument = next(c for c in data["calls"] if c["callee"] == "action")["arguments"][0]
    original = candidate(data, q, [{"span": argument["span"], "before": "2", "after": "4"}])
    saved = copy.deepcopy(original)
    atomized = atomize_candidates(corpus, data, [original])
    assert not atomized["unknowns"]
    atomic = atomized["candidates"][0]
    assert atomic["observation_id"] == q["id"]
    assert len(atomic["atomic_observation"]["neutralized_observation_ids"]) == 2
    assert "not (action(4) == 2)" in atomic["edits"][0]["after"]
    generated = emit(corpus, [atomic])
    assert not generated["unsupported"]
    namespace = {}
    exec(compile(generated["files"]["test_atomic.py"], "test_atomic.py", "exec"), namespace)
    namespace[generated["obligations"][0]["test_name"]]()
    assert namespace["events"] == ["open", 4, "closed"]
    namespace[generated["controls"][0]["test_name"]]()
    assert namespace["events"] == ["open", 2, "closed"]
    assert original == saved


def test_python_custom_truthiness_is_evaluated_exactly_once():
    corpus, data = fixture('''
events = []
class Truth:
    def __bool__(self):
        events.append("truth")
        return True
def test_seed():
    events.clear()
    assert Truth()
    assert events == ["truth"]
''')
    q = data["observations"][-1]
    atomic = atomize_candidates(corpus, data, [candidate(data, q)])["candidates"][0]
    emitted = emit(corpus, [atomic])
    namespace = {}
    exec(compile(emitted["files"]["test_atomic.py"], "test_atomic.py", "exec"), namespace)
    namespace[emitted["obligations"][0]["test_name"]]()
    assert namespace["events"] == ["truth"]


def test_effectful_messages_and_nonselected_exception_contexts_remain_unknown():
    corpus, data = fixture('''
def test_seed():
    assert first(), diagnostic()
    assert second() == 2
''')
    result = atomize_candidates(corpus, data, [candidate(data, data["observations"][-1])])
    assert not result["candidates"]
    assert result["unknowns"][0]["reason"] == "effectful_python_assertion_message"
    corpus, data = fixture('''
import pytest
def test_seed():
    with pytest.raises(ValueError):
        first()
    assert second() == 2
''')
    q = next(o for o in data["observations"] if o.get("predicate") != "raises")
    result = atomize_candidates(corpus, data, [candidate(data, q)])
    assert not result["candidates"]
    assert result["unknowns"][0]["reason"] == "python_non_direct_assertion_not_neutralized"


def test_typescript_eager_assertion_keeps_actual_action():
    corpus, data = fixture('''
test("actions", () => {
  expect(action(2)).toBe(2);
  expect(count).toBe(1);
});
''', "typescript", "atomic.test.ts")
    q = data["observations"][-1]
    argument = next(c for c in data["calls"] if c["callee"] == "action")["arguments"][0]
    result = atomize_candidates(corpus, data, [candidate(data, q, [{"span": argument["span"], "before": "2", "after": "4"}])])
    assert not result["unknowns"]
    emitted = emit(corpus, result["candidates"])
    assert not emitted["unsupported"]
    assert "(action(4));" in emitted["files"]["atomic.test.ts"]
    assert "expect(count).toBe(1)" in emitted["files"]["atomic.test.ts"]


def test_typescript_lazy_matcher_and_effectful_expected_are_not_dropped():
    for first in ["expect(() => action()).toThrow()", "expect(action()).toEqual(buildExpected())"]:
        corpus, data = fixture('test("case", () => { ' + first + '; expect(count).toBe(1); });', "typescript", "atomic.test.ts")
        result = atomize_candidates(corpus, data, [candidate(data, data["observations"][-1])])
        assert not result["candidates"]
        assert result["unknowns"]


def test_go_failure_guard_keeps_initializer_and_condition():
    corpus, data = fixture('''package example
import "testing"
func TestActions(t *testing.T) {
    if value := action(2); value != 2 { t.Fatal("first") }
    if count != 1 { t.Fatal("count") }
}
''', "go", "atomic_test.go")
    q = data["observations"][-1]
    argument = next(c for c in data["calls"] if c["callee"] == "action")["arguments"][0]
    result = atomize_candidates(corpus, data, [candidate(data, q, [{"span": argument["span"], "before": "2", "after": "4"}])])
    assert not result["unknowns"]
    emitted = emit(corpus, result["candidates"])
    assert not emitted["unsupported"]
    assert 'if value := action(4); value != 2 {}' in emitted["files"]["atomic_test.go"]
    assert 'if count != 1 { t.Fatal("count") }' in emitted["files"]["atomic_test.go"]


def test_program_selection_uses_dependence_and_rotates_observations():
    corpus, data = fixture('''
def test_seed():
    value = action(2)
    assert value.left == 1
    assert value.right == 2
''')
    argument = next(c for c in data["calls"] if c["callee"] == "action")["arguments"][0]
    originals = [dict(candidate(data, edits=[{"span": argument["span"], "before": "2", "after": str(n)}]), id="change_" + str(n)) for n in (3, 4)]
    result = atomize_candidates(corpus, data, originals, AtomicBudget(max_q_per_candidate=1))
    assert [c["observation_id"] for c in result["candidates"]] == [o["id"] for o in data["observations"]]
    assert all(c["atomic_observation"]["selection"] == "edited_input_may_dependence_then_observation_rotation" for c in result["candidates"])


def test_semantic_v2_sees_only_selected_expected_hole_and_original_input_slots():
    corpus, data = fixture('''
def test_seed():
    assert action(2) == 2
    assert observed() == 5
''')
    q = data["observations"][-1]
    argument = next(c for c in data["calls"] if c["callee"] == "action")["arguments"][0]
    atomized = atomize_candidates(corpus, data, [candidate(data, q, [{"span": argument["span"], "before": "2", "after": "4"}])])
    request = prepare_requests(corpus, data, atomized["candidates"], "The selected observation is stable.")["requests"][0]
    assert len(request["offered"][0]["holes"]) == 1
    assert request["offered"][0]["holes"][0]["observation_id"] == q["id"]
    assert request["offered"][0]["pre"] == [5]
    assert request["offered"][0]["arg"] == [4]
    wire = json.loads(request["prompt"])
    assert wire["candidates"][0]["q"]["assertion"] == "assert observed() == 5"
    assert wire["candidates"][0]["q"]["other_checks_neutralized"] == 1


def test_missing_pinned_observation_and_conditional_q_are_explicit_unknown():
    corpus, data = fixture('''
def test_seed():
    if ready:
        assert action() == 2
''')
    original = candidate(data, data["observations"][0])
    result = atomize_candidates(corpus, data, [original])
    assert result["unknowns"][0]["reason"] == "selected_observation_control_or_callback_scope_unknown"
    original["relation"]["source_observation_id"] = "foreign-q"
    result = atomize_candidates(corpus, data, [original])
    assert result["unknowns"][0]["reason"] == "pinned_observation_not_owned_by_seed"
