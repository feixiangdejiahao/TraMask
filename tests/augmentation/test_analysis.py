"""Behavioral checks for the new prototype, independent of benchmark labels."""
import json

from anchor_retrieval.syntax import Source
from augmentation.program import build_program, evaluate_condition
from augmentation.search import search
from augmentation.pipeline import prepare, build_request


def patch(path, code):
    lines = code.splitlines()
    return "\n".join(["--- a/" + path, "+++ b/" + path, f"@@ -1,1 +1,{len(lines)} @@"] + ["+" + line for line in lines])


def analyze(files, changed="lib.py", language="python"):
    program = build_program([Source(p, code, language) for p, code in files.items()], patch(changed, files[changed]))
    return program, search(program)


CACHE = '''class Cache:
    def __init__(self):
        self.entries = {}
    def put(self, key, value):
        self.entries[key] = value
    def clear(self):
        self.entries.clear()
    def get(self, key):
        return self.entries[key]
'''


def families(result, family, where="candidates"):
    return [c for c in result[where] if c["family"] == family]


def test_single_state_handoff_is_found_in_separate_tests():
    _, result = analyze({"lib.py": CACHE, "test_lib.py": '''from lib import Cache
def test_write():
    cache = Cache()
    cache.put("a", 7)
def test_read():
    cache = Cache()
    cache.entries["a"] = 7
    assert cache.get("a") == 7
'''})
    rows = families(result, "state_handoff")
    assert any("Cache.put" in " ".join(r["function_ids"]) and "Cache.get" in " ".join(r["function_ids"]) for r in rows)
    assert all("__init__" not in " ".join(r["function_ids"]) for r in rows)


def test_joint_same_binding_is_screened_but_not_declared_adequate():
    _, result = analyze({"lib.py": CACHE, "test_lib.py": '''from lib import Cache
def test_roundtrip():
    cache = Cache()
    cache.put("a", 7)
    assert cache.get("a") == 7
'''})
    checked = families(result, "state_handoff", "screened")
    assert any("Cache.put" in " ".join(r["function_ids"]) for r in checked)
    assert all(r["status"].endswith("not_adequacy_proof") for r in checked)


def test_different_receiver_or_key_does_not_satisfy_joint_binding():
    for code in ['''from lib import Cache
def test_roundtrip():
    a = Cache()
    b = Cache()
    a.put("a", 7)
    assert b.get("a") == 7
''', '''from lib import Cache
def test_roundtrip():
    a = Cache()
    a.put("a", 7)
    assert a.get("b") == 7
''']:
        _, result = analyze({"lib.py": CACHE, "test_lib.py": code})
        rows = families(result, "state_handoff")
        assert any("Cache.put" in " ".join(r["function_ids"]) and "Cache.get" in " ".join(r["function_ids"]) for r in rows)


def test_multi_relation_search_does_not_depend_on_single_relation_failure():
    _, result = analyze({"lib.py": CACHE, "test_lib.py": '''from lib import Cache
def test_roundtrip():
    cache = Cache()
    cache.put("a", 7)
    assert cache.get("a") == 7
def test_reset():
    cache = Cache()
    cache.clear()
'''})
    assert families(result, "state_handoff", "screened")
    rows = families(result, "state_composition")
    assert rows and all(r["scope"] == "multi_relation" for r in rows)
    assert all(r["shared_context"]["expansion_reason"] for r in rows)


def test_two_order_witnesses_reduce_duplicate_composition_candidate():
    _, result = analyze({"lib.py": CACHE, "test_lib.py": '''from lib import Cache
def test_first():
    cache = Cache()
    cache.put("a", 7)
    cache.clear()
    assert cache.get("a") is None
def test_second():
    cache = Cache()
    cache.clear()
    cache.put("a", 7)
    assert cache.get("a") == 7
'''})
    # Source evidence, deliberately not an assertion that these toy expectations are valid.
    assert families(result, "state_composition", "screened")
    assert not families(result, "state_composition")


def test_guard_joint_input_activation_and_negative_control():
    lib = "def choose(a, b):\n    if a > 0 and b > 0:\n        return 1\n    return 0\n"
    files = {"lib.py": lib, "test_lib.py": "from lib import choose\ndef test_one():\n    assert choose(1, 0) == 0\n    assert choose(0, 1) == 0\n"}
    _, result = analyze(files)
    rows = families(result, "guard_activation")
    assert len(rows) == 1
    assert rows[0]["evidence"]["missing_outcomes"] == [True]
    files["test_lib.py"] += "    assert choose(1, 1) == 1\n"
    _, result = analyze(files)
    assert not families(result, "guard_activation")
    assert families(result, "guard_activation", "screened")


def test_unknown_guard_input_is_not_silently_assigned_false():
    assert evaluate_condition("a > 0 and b > 0", {"a": 1}) == {"known": False}
    assert evaluate_condition("dangerous()", {}) == {"known": False}
    assert evaluate_condition("a > 0 && b > 0", {"a": 1, "b": 0}) == {"known": True, "value": False}


def test_rebound_result_is_not_counted_as_observation():
    _, result = analyze({"lib.py": "def compute(x):\n    return x * 2\n", "test_lib.py": '''from lib import compute
def test_result():
    value = compute(2)
    value = 9
    assert value == 9
'''})
    assert families(result, "result_observation")


def test_partial_return_observation_is_retained():
    _, result = analyze({"lib.py": "def compute(x):\n    return {'value': x * 2, 'status': 'ok'}\n", "test_lib.py": '''from lib import compute
def test_result():
    value = compute(2)
    assert value.status == 'ok'
'''})
    rows = families(result, "result_observation")
    assert rows[0]["evidence"]["missing_fields"] == ["value"]


def test_dictionary_projection_and_non_null_checks_do_not_cover_all_fields():
    lib = "def compute(x):\n    return {'value': x * 2, 'status': 'ok'}\n"
    for assertion in ["assert value['status'] == 'ok'", "assert value is not None"]:
        _, result = analyze({"lib.py": lib, "test_lib.py": "from lib import compute\ndef test_result():\n value = compute(2)\n " + assertion + "\n"})
        assert "value" in families(result, "result_observation")[0]["evidence"]["missing_fields"]
    _, result = analyze({"lib.py": lib, "test_lib.py": "from lib import compute\ndef test_result():\n value = compute(2)\n assert value == {'value': 4, 'status': 'ok'}\n"})
    assert not families(result, "result_observation")


def test_formal_state_is_joined_by_shared_actual_not_parameter_spelling():
    lib = '''def put(store, key, value):
    store[key] = value
def get(data, key):
    return data[key]
def process(store):
    put(store, 'a', 1)
    return get(store, 'a')
'''
    tests = '''from lib import put, get
def test_joint():
    cache = {}
    put(cache, 'a', 1)
    assert get(cache, 'a') == 1
'''
    _, result = analyze({"lib.py": lib, "test_lib.py": tests})
    assert families(result, "state_handoff", "screened")
    changed = tests.replace("assert get(cache, 'a')", "other = {}\n    assert get(other, 'a')")
    _, result = analyze({"lib.py": lib, "test_lib.py": changed})
    assert families(result, "state_handoff")


PROJECTION_TS = '''export function encode(e) { return e.id; }
export function evaluate(e) { return e.kind === 'and' ? e.id : -e.id; }
export function query(e) { const key = encode(e); return evaluate(e); }
'''


def test_typescript_projection_difference_is_derived_from_shared_actual():
    _, result = analyze({"lib.ts": PROJECTION_TS,
        "lib.test.ts": "import {query} from './lib'; test('one', () => { expect(query({id: 1, kind: 'and'})).toBe(1); });"},
        changed="lib.ts", language="typescript")
    rows = families(result, "projection_difference")
    assert len(rows) == 1
    assert rows[0]["evidence"]["retained_fields"] == ["id"]
    assert rows[0]["evidence"]["additional_fields"] == ["kind"]
    assert rows[0]["scope"] == "multi_relation"


def test_unrelated_formals_do_not_create_projection_composition():
    _, result = analyze({"lib.ts": PROJECTION_TS.replace("encode(e); return evaluate(e)", "encode(e); return evaluate(other)"),
        "lib.test.ts": "import {query} from './lib'; test('one', () => { expect(query({id: 1, kind: 'and'})).toBe(1); });"},
        changed="lib.ts", language="typescript")
    assert not families(result, "projection_difference")


def test_go_guard_activation_uses_resolved_call_arguments():
    lib = "package demo\nfunc Choose(a, b int) int { if a > 0 && b > 0 { return 1 }; return 0 }\n"
    tests = '''package demo
import "testing"
func TestChoose(t *testing.T) {
    if Choose(1, 0) != 0 { t.Fatal("wrong") }
    if Choose(0, 1) != 0 { t.Fatal("wrong") }
}
'''
    _, result = analyze({"lib.go": lib, "lib_test.go": tests}, changed="lib.go", language="go")
    rows = families(result, "guard_activation")
    assert rows and rows[0]["evidence"]["missing_outcomes"] == [True]


def test_void_state_updates_do_not_generate_result_only_gap():
    _, result = analyze({"lib.py": CACHE, "test_lib.py": "from lib import Cache\ndef test_put():\n cache = Cache()\n cache.put('a', 1)\n"})
    assert not families(result, "result_observation")


def test_inline_mixed_key_containers_are_not_shared_object_evidence():
    lib = "def put(store, key, value):\n store[key] = value\ndef get(store, key):\n return store[key]\n"
    tests = "from lib import put, get\ndef test_separate():\n put({1: 'a', 'k': 'b'}, 'k', 'x')\n assert get({1: 'a', 'k': 'b'}, 'k') == 'b'\n"
    program, result = analyze({"lib.py": lib, "test_lib.py": tests})
    assert any(c["targets"] for c in program["calls"])
    assert not families(result, "state_handoff", "screened")


def test_prepare_recovers_public_temporary_validation_and_never_executes_it(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    code = "def choose(a, b):\n    if a > 0 and b > 0:\n        return 1\n    return 0\n"
    (repo / "lib.py").write_text(code)
    trajectory = {"final_metrics": {"hidden": "SECRET_SCORE"}, "steps": [{
        "step_id": 4, "message": "Read lib.py and validate choose.", "reasoning_content": "SECRET_REASONING",
        "tool_calls": [{"arguments": {"cmd": "cat > /tmp/validation.py <<'PY'\nfrom lib import choose\nassert choose(1, 0) == 0\nPY\ntouch SHOULD_NEVER_EXIST"}}],
        "observation": {"results": [{"content": "public feedback"}]}}, {
        "step_id": 5, "tool_calls": [{"arguments": {"cmd": "python /tmp/validation.py"}}],
        "observation": {"results": [{"content": "standalone validation feedback"}]}}]}
    prepared = prepare(repo, patch("lib.py", code), "Return 1 iff both inputs are positive.", trajectory)
    assert prepared["counts"]["historical_test_sources"]
    assert prepared["counts"]["tests"]
    assert not (repo / "SHOULD_NEVER_EXIST").exists()
    assert "SECRET_REASONING" not in json.dumps(prepared)
    assert "SECRET_SCORE" not in json.dumps(prepared)
    rows = families(prepared, "guard_activation")
    assert rows
    request = build_request(prepared, rows[0]["id"])
    assert "public feedback" in request["prompt"]
    assert "standalone validation feedback" in request["prompt"]
    assert "current patch's" in request["system"]


def test_existing_joint_test_is_retained_for_execution_review(tmp_path):
    lib = "def choose(a, b):\n    if a > 0 and b > 0:\n        return 1\n    return 0\n"
    (tmp_path / "lib.py").write_text(lib)
    (tmp_path / "test_lib.py").write_text("from lib import choose\ndef test_joint():\n assert choose(1, 1) == 1\n assert choose(0, 1) == 0\n")
    prepared = prepare(tmp_path, patch("lib.py", lib), "Both inputs must be positive.")
    reviews = families(prepared, "guard_activation")
    assert len(reviews) == 1
    assert reviews[0]["review_focus"] == "existing_test_execution"
    assert prepared["counts"]["execution_reviews"] == 1
    payload = json.loads(build_request(prepared, reviews[0]["id"])["prompt"])
    assert payload["related_tests"]
    assert all(t["execution_status"] == "not_inferred_from_source" for t in payload["related_tests"])


def test_candidate_search_does_not_read_manual_labels_or_outcomes(tmp_path):
    (tmp_path / "lib.py").write_text(CACHE)
    (tmp_path / "test_lib.py").write_text("from lib import Cache\ndef test_put():\n c = Cache()\n c.put('x', 1)\n")
    change = patch("lib.py", CACHE)
    one = prepare(tmp_path, change, "Contract")
    (tmp_path / "manual_labels.json").write_text('{"gap":"SECRET"}')
    two = prepare(tmp_path, change, "Contract", {"final_metrics": {"resolved": True}})
    assert one["candidates"] == two["candidates"]


def test_removed_dependency_is_preserved_as_a_question(tmp_path):
    base, current = tmp_path / "base", tmp_path / "current"
    base.mkdir(); current.mkdir()
    old = "def normalize(x):\n return x.strip()\ndef process(x):\n return normalize(x)\n"
    new = "def normalize(x):\n return x.strip()\ndef process(x):\n return x\n"
    for directory, code in [(base, old), (current, new)]:
        (directory / "lib.py").write_text(code)
        (directory / "test_lib.py").write_text("from lib import process\ndef test_process():\n assert process('a') == 'a'\n")
    prepared = prepare(current, patch("lib.py", new), "Strip surrounding spaces.", base_repository=base)
    rows = families(prepared, "removed_dependency")
    assert rows and rows[0]["relations"][0]["version"] == "base"
    assert "normalize" in build_request(prepared, rows[0]["id"])["prompt"]


def test_real_value_handoff_is_distinct_from_separate_input_fixtures():
    lib = '''def produce(x):
    return {'value': x}
def consume(item):
    return item['value']
def process(x):
    item = produce(x)
    return consume(item)
'''
    tests = '''from lib import produce, consume, process
def test_producer():
    assert produce(1) == {'value': 1}
def test_consumer():
    assert consume({'value': 1}) == 1
'''
    _, result = analyze({"lib.py": lib, "test_lib.py": tests})
    assert families(result, "value_handoff")
    _, joint = analyze({"lib.py": lib, "test_lib.py": tests + "def test_joint():\n    assert process(2) == 2\n"})
    assert families(joint, "value_handoff", "screened")


def test_data_composition_retains_middle_semantics_but_not_plain_helper_depth():
    lib = '''def produce(x):
    return {'value': x}
def transform(item):
    return item['value'] + 1
def consume(x):
    return x * 2
def process(x):
    first = produce(x)
    second = transform(first)
    return consume(second)
'''
    _, result = analyze({"lib.py": lib, "test_lib.py": "from lib import process\ndef test_process():\n assert process(1) == 4\n"})
    rows = families(result, "value_composition")
    assert rows and len(rows[0]["relations"]) == 2
    plain = "def a(x):\n return b(x)\ndef b(x):\n return c(x)\ndef c(x):\n return x\n"
    _, result = analyze({"lib.py": plain, "test_lib.py": "from lib import a\ndef test_a():\n assert a(1) == 1\n"})
    assert not families(result, "value_composition")


def test_data_composition_does_not_join_independent_middle_invocations():
    lib = '''def produce(x):
    return {'value': x}
def transform(item):
    return item['value'] + 1
def consume(x):
    return x * 2
def process(x):
    first = produce(x)
    unused = transform(first)
    independent = transform({'value': 99})
    return consume(independent)
'''
    _, result = analyze({"lib.py": lib, "test_lib.py": "from lib import process\ndef test_process():\n assert process(1) == 200\n"})
    assert not families(result, "value_composition")
