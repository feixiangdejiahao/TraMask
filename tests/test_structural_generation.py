"""Semantic construction checks for the context-lifting adapters."""
from pathlib import Path

from combination_testing.structural import (
    _guest_free_identifiers,
    _toplevel_bindings,
    generate_go,
    generate_typescript,
    mine_go_programs,
    mine_ts_schemas,
)


def retrieval(code: str, path: str = "example_test.go") -> dict:
    return {"selected_tests": [{"rank": 1, "path": path, "line": 40,
                                "test_id": "arbitrary", "name": "arbitrary", "code": code}]}


def test_scope_scan_ignores_nested_declarations_and_text():
    bindings = _toplevel_bindings('''
counter := 0
label := "fake := func() {}"
increase := func(delta) { local := delta; counter += local; return counter }
// comment := 9
items := {inside: func() { shadow := 1; return shadow }}
''')
    assert [item["name"] for item in bindings] == ["counter", "label", "increase", "items"]
    assert [item["name"] for item in bindings if item["scalar"]] == ["counter"]
    assert [item["name"] for item in bindings if item["function"]] == ["increase"]


def test_scope_lift_synthesizes_shared_observer_without_expected_value():
    data = retrieval('func TestAnything(t *testing.T) { source := `state := 17\nbump := func() { state++; return state }` }')
    programs, rejected = mine_go_programs(data)
    assert not rejected
    assert len(programs) == 1
    assert '"__observe_state": func() { return state }' in programs[0]["lifted"]
    assert programs[0]["source"] in programs[0]["lifted"]
    assert "18" not in programs[0]["lifted"]


def test_free_binding_precondition_handles_parameters_members_and_map_keys():
    code = '''
state := 0
f := func(items, ...rest) {
  for index, value in items { state += value }
  return {count: len(rest), item: items.field}
}
'''
    assert _guest_free_identifiers(code, {"len"}) == []
    assert _guest_free_identifiers(code.replace("len(rest)", "host_callback(rest)"), {"len"}) == ["host_callback"]


def test_go_seed_selection_respects_rank_and_deduplicates():
    code = 'func TestAnything(t *testing.T) { source := `f := func() { return 4 }` }'
    data = retrieval(code)
    data["selected_tests"] *= 3
    programs, _ = mine_go_programs(data, top_k=2)
    assert len(programs) == 1
    data["selected_tests"][2] = {**data["selected_tests"][2], "code": code.replace("4", "19")}
    assert len(mine_go_programs(data, top_k=2)[0]) == 1
    assert len(mine_go_programs(data, top_k=3)[0]) == 2


def test_go_module_import_and_runtime_do_not_depend_on_repository_name(tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.org/interpreter\n")
    artifact = generate_go(tmp_path, retrieval('func TestX(t *testing.T) { s:=`x := 3\nf := func() { x++; return x }` }'))
    content = artifact["files"]["combination_context_generated_test.go"]
    assert 'tengo "example.org/interpreter"' in content
    assert "host_guest" in content and "clone_fresh" in content
    assert "CC_RESULT" in content
    assert "control_call" in content and "control_clone" in content
    assert "ccChildren" in content


def test_schema_seed_follows_parse_arguments_instead_of_names():
    data = retrieval('''test('renamed', () => {
const Weird = recursive(object({ nodes: array(Recur), text: string() }));
const payload = { nodes: [], text: 'sample' };
expect(parse(Weird, payload)).toStrictEqual(payload);
});''', "some.test.ts")
    schemas = mine_ts_schemas(data)
    assert len(schemas) == 1
    assert schemas[0]["input"] == "{ nodes: [], text: 'sample' }"
    assert "array(Recur)" in schemas[0]["body"]


def test_ts_only_migrates_pure_shape_preserving_donors(tmp_path: Path):
    test_dir = tmp_path / "library" / "src" / "actions"
    test_dir.mkdir(parents=True)
    (test_dir / "donors.test.ts").write_text('''
const useful = transform((value: {x: string}) => ({...value, extra: 42}));
const shrink = transform((value: string) => value.length);
const sideEffect = transform((value: object) => ({...value, extra: run()}));
const overwritten = transform((value: object) => ({extra: 42, ...value}));
''')
    data = retrieval('''test('sample', () => {
const S = recursive(object({child: array(Recur)}));
const data = {child: [{child: []}]};
expect(parse(S, data)).toStrictEqual(data);
});''', "schemas.test.ts")
    artifact = generate_typescript(tmp_path, data)
    assert len(artifact["metadata"]["donors"]) == 1
    assert len(artifact["metadata"]["obligations"]) == 2
    control, combined = artifact["metadata"]["obligations"]
    assert control["is_control"]
    assert combined["control_id"] == control["id"]
    code = artifact["files"]["library/src/combination.context.generated.test.ts"]
    assert "...__cc_value, extra: 42" in code
    assert "parseAsync(explicit" in code
    assert "expect(actual).toStrictEqual(expected)" in code
    assert "extra: 42, child" not in code
