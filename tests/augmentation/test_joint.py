import json

from anchor_retrieval.syntax import Source
from augmentation.program import build_program
from augmentation.joint import search_joint
from augmentation.pipeline import prepare, build_request
from augmentation.history import history_chain, index_history
from augmentation.scopes import test_scope as collect_scope


def patch(path, code):
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1,{len(code.splitlines())} @@\n" + "\n".join("+" + row for row in code.splitlines())


def analyze(code, test, language="python", suffix="py"):
    path = "lib." + suffix
    tpath = "test_lib.py" if language == "python" else "lib_test.go" if language == "go" else "lib.test.ts"
    program = build_program([Source(path, code, language), Source(tpath, test, language)], patch(path, code))
    return program, search_joint(program, program["behavior_graph"])


def rows(result, family):
    return [row for row in result["candidates"] if row["family"] == family]


def test_joint_true_case_is_not_inferred_from_two_entry_calls():
    code = "def choose(a, b):\n if a > 0 and b > 0:\n  return 1\n return 0\n"
    test = "from lib import choose\ndef test_parts():\n assert choose(1, 0) == 0\n assert choose(0, 1) == 0\n"
    _, result = analyze(code, test)
    candidate = rows(result, "joint_conditions")[0]
    assert any(all(cell["conditions"].values()) for cell in candidate["behavior"]["combinations"]["missing"])
    assert len({row["entry_call"] for row in candidate["test_scope"]["rows"]}) == 2


def test_three_way_gap_survives_complete_pairwise_source_checks():
    code = "def choose(a, b, c):\n if a and b and c:\n  return 1\n return 0\n"
    calls = "\n".join(f" assert choose({a}, {b}, {c}) == 0" for a, b, c in [(0,0,0),(0,1,1),(1,0,1),(1,1,0)])
    _, result = analyze(code, "from lib import choose\ndef test_pairs():\n" + calls + "\n")
    candidate = next(c for c in rows(result, "joint_conditions") if c["behavior"]["condition_dimensions"] == 3)
    assert any(all(cell["conditions"].values()) for cell in candidate["behavior"]["combinations"]["missing"])
    assert candidate["behavior"]["condition_dimensions"] != candidate["behavior"]["relation_count"]


def test_unknown_input_keeps_unknown_cells_instead_of_missing_or_covered():
    code = "def choose(a, b):\n if a and b:\n  return 1\n return 0\n"
    _, result = analyze(code, "from lib import choose\ndef test_dynamic():\n assert choose(get_a(), get_b()) == 1\n")
    cells = rows(result, "joint_conditions")[0]["behavior"]["combinations"]
    assert cells["unknown"] and not cells["checked"] and not cells["missing"]


def test_scope_bound_preserves_inventory_of_other_related_tests():
    code = "def choose(a, b):\n if a and b:\n  return 1\n return 0\n"
    tests = "from lib import choose\ndef test_first():\n assert choose(1,0)==0\ndef test_second():\n assert choose(0,1)==0\n"
    program, result = analyze(code, tests)
    candidate = rows(result, "joint_conditions")[0]
    scope = collect_scope(program, program["behavior_graph"], candidate["function_ids"], candidate["behavior"]["conditions"], max_rows=1)
    assert len(scope["rows"]) == 1 and scope["truncated"]
    assert len(scope["test_ids"]) == 2


def test_earlier_exit_does_not_turn_later_arguments_into_a_checked_combination():
    code = "def later(a, b):\n if a and b:\n  return 1\n return 0\ndef entry(stop, a, b):\n if stop:\n  return 0\n return later(a, b)\n"
    _, result = analyze(code, "from lib import entry\ndef test_early():\n assert entry(True, True, True) == 0\n")
    candidate = next(c for c in rows(result, "joint_conditions") if any(d["expression"] == "a" for d in c["behavior"]["conditions"]))
    cells = candidate["behavior"]["combinations"]
    assert not any(all(cell["conditions"].values()) for cell in cells["checked"])
    assert any(all(cell["conditions"].values()) for cell in cells["unknown"])
    assert rows(result, "blocked_continuation")


DEFAULT_TS = """export function required(item, options) {
 if (options.mode !== 'put') return true;
 return item.name !== undefined;
}
export function parse(item, options = {}) {
 const { mode = 'put' } = options;
 return required(item, options);
}
"""


def test_default_propagation_exposes_omitted_input_without_merging_call_contexts():
    _, result = analyze(DEFAULT_TS, "import {parse} from './lib'; test('one',()=>{ expect(parse({}, {mode:'put'})).toBe(false); });", "typescript", "ts")
    candidate = rows(result, "default_propagation")[0]
    presence = next(d["id"] for d in candidate["behavior"]["conditions"] if d["kind"] == "presence")
    assert any(cell["conditions"][presence] is False for cell in candidate["behavior"]["combinations"]["missing"])
    assert any(row["conditions"][presence] == {"known": True, "value": True} for row in candidate["test_scope"]["rows"])


def test_omitted_and_explicit_undefined_are_distinct_source_inputs():
    _, result = analyze(DEFAULT_TS, "import {parse} from './lib'; test('one',()=>{ expect(parse({})).toBe(false); expect(parse({}, {mode:undefined})).toBe(false); });", "typescript", "ts")
    candidate = rows(result, "default_propagation")[0]
    presence = next(d["id"] for d in candidate["behavior"]["conditions"] if d["kind"] == "presence")
    known = {r["conditions"][presence]["value"] for r in candidate["test_scope"]["rows"] if r["conditions"][presence].get("known")}
    assert known == {True, False}
    assert any("undefined" in json.dumps(r["inputs"]) for r in candidate["test_scope"]["rows"])


def test_destructured_parameter_remains_unknown_without_breaking_extraction():
    code = "export function run({x}, options) { if (x && options.ok) return true; return false; }\n"
    _, result = analyze(code, "import {run} from './lib'; test('one',()=>{ expect(run({x:1},{ok:true})).toBe(true); });", "typescript", "ts")
    assert rows(result, "joint_conditions")
    assert "null:" not in json.dumps(result)


def test_loop_alias_links_declaration_to_runtime_field(tmp_path):
    code = "package demo\nfunc Build(spec Spec) { ch := spec.Hash; for _, cookie := range ch.Cookies { Parse(cookie.TTL) } }\n"
    (tmp_path / "lib.go").write_text(code)
    (tmp_path / "schema.yaml").write_text("properties:\n  hash:\n    properties:\n      cookies:\n        items:\n          properties:\n            ttl:\n              pattern: '^[0-9]+s$'\n")
    result = prepare(tmp_path, patch("lib.go", code), "Accept decimal duration.")
    candidates = rows(result, "declaration_flow")
    assert candidates
    assert any("spec.Hash.Cookies.TTL" in node.get("input_origin_reads", []) for c in candidates for node in c["behavior"]["operations"])


def test_typed_state_connects_later_consumers_with_instance_uncertainty():
    code = """export class Query {
 state: State;
 restore(s: State) { this.state = s; }
}
export class Observer {
 query: Query;
 read() { return this.query.state; }
}
"""
    program, result = analyze(code, "", "typescript", "ts")
    links = [e for e in program["behavior_graph"]["edges"] if e["kind"] == "shared_state"]
    assert any("instance_review" in e["certainty"] for e in links)
    assert rows(result, "state_continuation")


def test_changed_transition_connects_unchanged_state_write_and_later_reader():
    code = """export class Query {
 state: State;
 restore(s: State) {
  const next = s;
  this.state = next;
 }
}
export class Observer {
 query: Query;
 read() { return this.query.state; }
}
"""
    program = build_program([Source("lib.ts", code, "typescript")], "--- a/lib.ts\n+++ b/lib.ts\n@@ -4 +4 @@\n-  const next = old;\n+  const next = s;\n")
    links = [e for e in program["behavior_graph"]["edges"] if e["kind"] == "shared_state"]
    assert any("instance_review" in e["certainty"] for e in links)


def test_callable_assertion_entry_and_blocked_output_are_both_retained():
    code = "import sys\ndef run(warm, emit):\n if warm:\n  sys.exit(0)\n emit()\n"
    test = "from lib import run\nimport unittest\nclass TestCLI(unittest.TestCase):\n def test_warm(self):\n  self.assertRaisesRegex(SystemExit, '0', run, True, print)\n"
    program, result = analyze(code, test)
    assert any(c.get("callable_helper") == "self.assertRaisesRegex" and c["targets"] for c in program["calls"])
    candidates = rows(result, "blocked_continuation")
    assert candidates
    assert any("emit()" in n["code"] for c in candidates for n in c["behavior"]["operations"])
    assert any(c["test_ids"] for c in candidates)


def test_callable_entry_resolves_imported_submodule_not_same_named_neighbor():
    code = "import sys\ndef main(warm):\n if warm:\n  sys.exit(0)\n print('report')\n"
    sources = [Source("pkg/cli/main.py", code, "python"),
               Source("pkg/cli/other.py", "def main():\n pass\n", "python"),
               Source("tests/test_cli.py", "from pkg.cli import main as cli\nimport unittest\nclass TestCLI(unittest.TestCase):\n def test_exit(self):\n  self.assertRaisesRegex(SystemExit, '0', cli.main, True)\n", "python")]
    program = build_program(sources, patch("pkg/cli/main.py", code))
    recovered = [c for c in program["calls"] if c.get("callable_helper")]
    assert len(recovered) == 1
    assert all(fid.startswith("pkg/cli/main.py:") for fid in recovered[0]["targets"])


def test_go_method_dispatch_preserves_possible_targets_without_proving_identity():
    code = "package demo\ntype Obj interface { Read() int }; type A struct { X int }; type B struct { X int }\nfunc (a *A) Read() int { return a.X }\nfunc (b *B) Read() int { return b.X }\nfunc Use(o Obj) int { return o.Read() }\n"
    program, _ = analyze(code, "package demo\n", "go", "go")
    call = next(n for n in program["behavior_graph"]["nodes"].values() if n["kind"] == "call" and n["callee"] == "o.Read")
    assert len(call["targets"]) == 2
    assert "requires_type_review" in call["resolution"]


def test_repeated_pointer_copy_exposes_sharing_without_assuming_a_bug():
    code = "package demo\nfunc Copy(o *Thing) *Thing { out := &Thing{}; for i, v := range o.Free { out.Free[i] = &Ptr{Value: v.Value} }; return out }\n"
    _, result = analyze(code, "package demo\n", "go", "go")
    candidates = rows(result, "shared_copy")
    assert candidates and candidates[0]["behavior"]["condition_dimensions"] == 2
    assert candidates[0]["status"] != "confirmed_bug"


def test_declaration_and_runtime_are_connected_by_a_field_path(tmp_path):
    code = "def parse(config):\n return duration(config.cookies.ttl)\n"
    (tmp_path / "lib.py").write_text(code)
    (tmp_path / "test_lib.py").write_text("from lib import parse\ndef test_runtime():\n assert parse(make_config()) == 1\n")
    (tmp_path / "schema.yaml").write_text("properties:\n  cookies:\n    properties:\n      ttl:\n        pattern: '^[0-9]+s$'\n")
    result = prepare(tmp_path, patch("lib.py", code), "Accept fractional durations.")
    candidate = rows(result, "declaration_flow")[0]
    request = json.loads(build_request(result, candidate["id"])["prompt"])
    assert candidate["evidence"]["declaration"]["field_path"] == "cookies.ttl"
    assert any(s["path"] == "schema.yaml" for s in request["source_excerpts"])
    assert "schema.yaml" in result["source_receipts"]


def test_history_keeps_execution_before_and_after_relevant_edit():
    steps = [{"tool_calls":[{"arguments":{"cmd":cmd}}],"observation":{"text":str(i)}} for i,cmd in enumerate([
        "sed -n '1,50p' lib.py", "python3 -m pytest", "apply_patch lib.py", "python3 -m pytest"])]
    chain = history_chain(index_history({"steps": steps}), ["lib.py"], ["choose"])
    assert chain["last_related_edit"] == 2
    assert chain["validation_after_last_edit"] == [3]
    assert chain["final_version_execution"].startswith("unknown")
    assert {1,2,3} <= {s["ordinal"] for s in chain["steps"]}


def test_prompt_bounds_preserve_explicit_omission_and_no_reference_inputs(tmp_path):
    code = "def choose(a, b):\n if a and b:\n  return 1\n return 0\n"
    (tmp_path / "lib.py").write_text(code)
    (tmp_path / "test_lib.py").write_text("from lib import choose\ndef test_one():\n assert choose(1, 0) == 0\n")
    result = prepare(tmp_path, patch("lib.py", code), "Both conditions are required.", {"metrics":{"secret":"NO_LEAK"}})
    request = build_request(result, result["candidates"][0]["id"])
    payload = json.loads(request["prompt"])
    assert "test_scope" in payload and "NO_LEAK" not in request["prompt"]
    assert "submitted_patch" not in payload
    assert payload["input_scope"]["all_related_tests"] >= len(payload["related_tests"])
