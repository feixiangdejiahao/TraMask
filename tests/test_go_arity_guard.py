import copy
import shutil
import subprocess

import pytest

from experimental.go_arity_guard import filter_candidates


def corpus(code, extra=None):
    sources = {"pkg/test_test.go": {"code": code, "language": "go"}}
    sources.update({path: {"code": content, "language": "go"} for path, content in (extra or {}).items()})
    return {"language": "go", "sources": sources}


def candidate(data, before, after, path="pkg/test_test.go", identifier="candidate"):
    code = data["sources"][path]["code"].encode()
    start = code.index(before.encode())
    return {"id": identifier, "edits": [{"span": {"path": path, "start_byte": start,
                                                 "end_byte": start+len(before.encode())},
                                         "before": before, "after": after, "role": "input"}]}


def decision(report):
    return report["records"][0]["calls"][0]


def test_fixed_required_parameter_cannot_be_deleted_and_inputs_are_immutable():
    data = corpus('''package sample
func setup(label string, files map[string]string) {}
func TestA(){setup("x", map[string]string{"a":"b"})}
''')
    row = candidate(data, 'setup("x", map[string]string{"a":"b"})', 'setup("x")')
    frozen = copy.deepcopy((data, row))
    report = filter_candidates(data, [row])
    assert not report["candidates"] and report["rejected"] == [row]
    assert decision(report)["signature"]["required"] == 2
    assert (data, row) == frozen


@pytest.mark.parametrize("parameters,call,after,required", [
    ("a,b,c int", "f(1,2,3)", "f(1,2)", 3),
    ("int, string", 'f(1,"a")', "f(1)", 2),
    ("a int, b,c string", 'f(1,"a","b")', 'f(1,"a")', 3),
])
def test_grouped_and_unnamed_parameters(parameters, call, after, required):
    data = corpus(f"package sample\nfunc f({parameters}){{}}\nfunc TestA(){{{call}}}")
    result = filter_candidates(data, [candidate(data, call, after)])
    assert result["counts"]["rejected"] == 1
    assert decision(result)["signature"]["required"] == required


def test_variadic_tail_may_be_omitted_but_fixed_prefix_must_remain():
    data = corpus('''package sample
func f(first string, rest ...map[string]int){}
func TestA(){f("a",map[string]int{"x":1})}
''')
    before = 'f("a",map[string]int{"x":1})'
    okay = candidate(data, before, 'f("a")', identifier="tail")
    invalid = candidate(data, before, 'f()', identifier="prefix")
    result = filter_candidates(data, [okay, invalid])
    assert result["candidates"] == [okay]
    assert result["rejected"] == [invalid]
    assert result["records"][0]["calls"][0]["signature"]["variadic"] is True


def test_empty_variadic_declaration_and_spread_are_counted_correctly():
    data = corpus('''package sample
func f(...int){}
func g(label string, rest ...int){}
func TestA(){f(1);g("x",1)}
''')
    rows = [candidate(data, "f(1)", "f()", identifier="empty"),
            candidate(data, 'g("x",1)', 'g("x",1,values...)', identifier="extra_before_spread")]
    result = filter_candidates(data, rows)
    assert result["candidates"] == rows[:1]
    assert result["rejected"] == rows[1:]


@pytest.mark.parametrize("setup,call,after", [
    ("var object Thing", 'object.Do(1,"x")', 'object.Do(1)'),
    ("object:=Thing{}", 'object.Do(1,"x")', 'object.Do(1)'),
    ("object:=&Thing{}", 'object.Do(1,"x")', 'object.Do(1)'),
    ("var object Thing", 'Thing.Do(object,1,"x")', 'Thing.Do(object,1)'),
])
def test_declared_method_receiver_uses_method_not_same_named_function(setup, call, after):
    data = corpus(f'''package sample
type Thing struct{{}}
func (t *Thing) Do(n int,s string){{}}
func Do(n int){{}}
func TestA(){{{setup};{call}}}
''')
    result = filter_candidates(data, [candidate(data, call, after)])
    assert result["counts"]["rejected"] == 1
    assert decision(result)["signature"]["receiver_type"] == "Thing"


def test_parameter_receiver_and_import_alias_resolve_explicit_module_path():
    data = corpus('''package sample
import other "example.org/project/lib"
func TestA(object *other.Box){object.Apply(1,2);other.Build(1,2)}
''', {"lib/library.go": '''package differently_named
type Box struct{}
func (*Box) Apply(a,b int){}
func Build(a,b int){}
''', "alien/library.go": "package differently_named\nfunc Build(a int){}"})
    frontend = {"module_resolution": {"go_modules": {"": "example.org/project"}}}
    rows = [candidate(data, "object.Apply(1,2)", "object.Apply(1)", identifier="method"),
            candidate(data, "other.Build(1,2)", "other.Build(1)", identifier="function")]
    result = filter_candidates(data, rows, frontend)
    assert result["counts"]["rejected"] == 2
    assert all(record["calls"][0]["signature"]["path"] == "lib/library.go" for record in result["records"])


def test_cross_package_same_name_does_not_supply_a_signature():
    data = corpus('''package same
import unrelated "example.org/unavailable"
func TestA(){unrelated.Run(1,2)}
''', {"other/file.go": "package same\nfunc Run(a,b int){}"})
    row = candidate(data, "unrelated.Run(1,2)", "unrelated.Run(1)")
    result = filter_candidates(data, [row])
    assert result["candidates"] == [row]
    assert decision(result)["status"] == "unsupported"
    assert decision(result)["reason"] == "unresolved_import_package"


def test_frontend_target_cannot_override_mismatched_import_identity():
    data = corpus('''package sample
import lib "example.org/missing"
func TestA(){lib.Run(1,2)}
''', {"other/file.go": "package other\nfunc Run(a,b int){}"})
    row = candidate(data, "lib.Run(1,2)", "lib.Run(1)")
    span = row["edits"][0]["span"]
    frontend = {"calls": [{"span": span, "targets": [{"resolved": True, "function_id": "wrong"}]}],
                "functions": [{"id": "wrong", "span": {"path": "other/file.go", "start_byte": 14}}]}
    result = filter_candidates(data, [row], frontend)
    assert result["candidates"] == [row]
    assert decision(result)["reason"] == "unresolved_import_package"


def test_ambiguous_source_declarations_are_not_picked_arbitrarily():
    data = corpus("package sample\nfunc TestA(){f(1,2)}", {
        "pkg/a.go": "package sample\nfunc f(a,b int){}",
        "pkg/b.go": "package sample\nfunc f(a int){}",
    })
    row = candidate(data, "f(1,2)", "f(1)")
    result = filter_candidates(data, [row])
    assert result["candidates"] == [row]
    assert decision(result)["reason"] == "ambiguous_declaration"


def test_same_package_other_file_resolves_but_external_test_package_does_not():
    data = corpus("package sample\nfunc TestA(){f(1,2)}", {
        "pkg/helper_test.go": "package sample\nfunc f(a,b int){}",
        "pkg/external_test.go": "package sample_test\nfunc f(a int){}",
        "unrelated/file.go": "package sample\nfunc f(a int){}",
    })
    result = filter_candidates(data, [candidate(data, "f(1,2)", "f(1)")])
    assert result["counts"]["rejected"] == 1
    assert decision(result)["signature"]["path"] == "pkg/helper_test.go"


def test_shadowed_function_parameter_is_not_confused_with_package_function():
    data = corpus('''package sample
func f(a,b int){}
func TestA(f func(...int)){f(1,2)}
''')
    result = filter_candidates(data, [candidate(data, "f(1,2)", "f(1)")])
    assert result["counts"]["rejected"] == 0
    assert decision(result)["reason"] == "unresolved_local_function_binding"


def test_local_function_literal_resolves_its_own_variadic_signature():
    data = corpus('''package sample
func f(a,b int){}
func TestA(){f:=func(values ...int){};f(1,2)}
''')
    result = filter_candidates(data, [candidate(data, "f(1,2)", "f(1)")])
    assert decision(result)["status"] == "accepted"
    assert decision(result)["resolution"] == "local_function_literal"


def test_unknown_receiver_does_not_match_an_unrelated_same_named_method():
    data = corpus('''package sample
type Box struct{}
func (Box) Apply(a,b int){}
func TestA(){x:=Factory();x.Apply(1,2)}
''')
    result = filter_candidates(data, [candidate(data, "x.Apply(1,2)", "x.Apply(1)")])
    assert result["counts"]["rejected"] == 0
    assert decision(result)["reason"] == "unresolved_receiver_type"


def test_range_variable_shadowing_type_is_not_a_method_expression():
    data = corpus('''package sample
type Box struct{}
func (Box) Apply(a,b int){}
func TestA(){for Box:=range values {Box.Apply(1,2)}}
''')
    result = filter_candidates(data, [candidate(data, "Box.Apply(1,2)", "Box.Apply(1)")])
    assert result["counts"]["rejected"] == 0
    assert decision(result)["reason"] == "unresolved_receiver_type"


def test_single_tuple_valued_call_argument_stays_unknown():
    data = corpus("package sample\nfunc f(a,b int){}\nfunc TestA(){f(1,2)}")
    result = filter_candidates(data, [candidate(data, "f(1,2)", "f(pair())")])
    assert result["counts"]["rejected"] == 0
    assert decision(result)["reason"] == "possible_multi_result_argument"


def test_partial_argument_deletion_and_unchanged_record_input():
    data = corpus('''package sample
func f(n int, xs map[string]int){}
func TestA(){f(1,map[string]int{"x":1})}
''')
    rows = [candidate(data, ',map[string]int{"x":1}', "", identifier="delete"),
            candidate(data, 'map[string]int{"x":1}', 'map[string]int{}', identifier="record")]
    result = filter_candidates(data, rows)
    assert result["rejected"] == rows[:1]
    assert result["candidates"] == rows[1:]
    assert result["records"][1]["status"] == "unchanged_arity"


@pytest.mark.skipif(shutil.which("go") is None, reason="Go compiler unavailable")
def test_retained_variadic_and_rejected_fixed_calls_agree_with_native_compiler(tmp_path):
    data = corpus('''package sample
func required(label string, files map[string]int){}
func optional(label string, files ...map[string]int){}
func TestA(){required("x",map[string]int{"x":1});optional("x",map[string]int{"x":1})}
''')
    rows = [candidate(data, 'required("x",map[string]int{"x":1})', 'required("x")', identifier="fixed"),
            candidate(data, 'optional("x",map[string]int{"x":1})', 'optional("x")', identifier="variadic")]
    report = filter_candidates(data, rows)
    assert report["rejected"] == rows[:1] and report["candidates"] == rows[1:]
    for row, expected_valid in zip(rows, [False, True]):
        edit = row["edits"][0]
        code = data["sources"][edit["span"]["path"]]["code"].replace(edit["before"], edit["after"])
        path = tmp_path / (row["id"] + ".go")
        path.write_text(code)
        result = subprocess.run([shutil.which("go"), "tool", "compile", "-o", str(tmp_path / (row["id"]+".o")), str(path)],
                                capture_output=True, text=True, timeout=20)
        assert (result.returncode == 0) is expected_valid, result.stdout + result.stderr
        if not expected_valid:
            assert "not enough arguments" in result.stdout + result.stderr
