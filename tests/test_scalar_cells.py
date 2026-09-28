"""Independent source programs for bounded scalar constraint enumeration."""
import ast

import pytest

from anchor_retrieval.syntax import Source
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relational_gap.scalar_cells import ScalarBudget, generate_scalar_cells


def build(code, language="python", path="test_sample.py", **kwargs):
    sources = [Source(path, code, language)] if isinstance(code, str) else [Source(p, text, language) for p, text in code.items()]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend, generate_scalar_cells(corpus, frontend, **kwargs)


def replacements(result):
    return {c["edits"][0]["after"] for c in result["candidates"]}


def test_go_alias_getter_opposite_keeps_explicit_unknown_neighbours():
    corpus, _, result = build('''package sample
import "testing"
type Stamp uint64
type Meter struct {}
func (m *Meter) Load() Stamp { return 10 }
var high Meter
func accepts(value Stamp) bool { return value < high.Load() }
func TestValue(t *testing.T) {
    seq := Stamp(9)
    if !accepts(seq+1) { t.Fatal(42) }
}
''', "go", "sample_test.go")
    assert replacements(result) == {"(seq+1) - 1", "(seq+1) + 1"}
    for candidate in result["candidates"]:
        relation = candidate["relation"]
        assert relation["construction"] == "unknown_boundary_neighbor"
        assert relation["counteroperand_status"] == "unrecoverable_or_nonlinear"
        assert relation["status"] == "hypothesis_runtime_relation_unconfirmed"
        assert relation["numeric_type"]["aliases"][0]["name"] == "Stamp"
        assert candidate["edits"][0]["after"].count("seq+1") == 1
        assert candidate["edits"][0]["before"] != "42"
    output = emit(corpus, result["candidates"])
    assert not output["unsupported"]
    assert not Source("sample_test.go", output["files"]["sample_test.go"], "go").root.has_error


def test_python_annotated_formals_and_two_hop_exact_boundary():
    corpus, frontend, result = build({
        "pkg/core.py": "def inner(value: int):\n    return value < 4\n",
        "pkg/wrapper.py": "from .core import inner\ndef wrap(value: int):\n    return inner(value + 1)\n",
        "tests/test_sample.py": "from pkg.wrapper import wrap\ndef test_value():\n    assert wrap(1) is True\n",
    })
    assert all(p["name"] == "value" for f in frontend["functions"] if f["name"] in {"inner", "wrap"} for p in f["parameters"])
    assert replacements(result) == {"2", "3", "4"}
    assert {c["relation"]["cell"]["boundary"] for c in result["candidates"]} == {3}
    assert {len(c["relation"]["binding_path"]) for c in result["candidates"]} == {2}
    output = emit(corpus, result["candidates"])
    assert not output["unsupported"]
    for path, text in output["files"].items():
        compile(text, path, "exec")


def test_go_alias_resolves_same_package_declaration_and_exact_rhs():
    _, _, result = build({
        "sample/types.go": "package sample\ntype Base uint64\ntype Stamp Base\n",
        "sample/core.go": "package sample\nfunc accepts(value Stamp) bool { return value <= 4 }\n",
        "sample/core_test.go": 'package sample\nimport "testing"\nfunc TestValue(t *testing.T) { if !accepts(2) { t.Fatal("bad") } }\n',
    }, "go")
    assert replacements(result) == {"3", "4", "5"}
    info = result["candidates"][0]["relation"]["numeric_type"]
    assert info["underlying"] == "uint64"
    assert [a["name"] for a in info["aliases"]] == ["Stamp", "Base"]


def test_source_mask_generates_only_observed_bit_operations():
    _, _, result = build('''package sample
import "testing"
type Flags uint64
const Active Flags = 1 << 3
func accepts(value Flags) bool { return value & Active != 0 }
func TestValue(t *testing.T) { if !accepts(8) { t.Fatal("bad") } }
''', "go", "mask_test.go")
    assert "(8) &^ 8" in replacements(result)
    assert all(c["relation"]["cell"]["mask"] == 8 for c in result["candidates"])
    assert all(c["relation"]["construction"].startswith("observed_mask_") for c in result["candidates"])


def test_python_truthy_bit_guard_uses_source_constant():
    _, _, result = build('''MASK = 4
def accepts(value: int):
    if value & MASK:
        return 1
    return 0
def test_value():
    assert accepts(0) == 0
''')
    assert "(0) | 4" in replacements(result)
    assert {c["relation"]["operator"] for c in result["candidates"]} == {"truthy_bit_test"}


def test_effectful_actual_call_is_never_repeated_or_replaced():
    _, _, result = build('''def accepts(value: int):
    return value < 4
def next_value():
    return 2
def test_value():
    assert accepts(next_value()) is True
''')
    assert not result["candidates"]
    assert result["counts"]["skipped"]["effectful_or_noninteger_actual"]


def test_numeric_named_python_function_is_not_a_pure_cast():
    _, _, result = build('''events = []
def int(value):
    events.append(value)
    return value
def accepts(value):
    return value < 4
def test_value():
    assert accepts(int(2)) is True
''')
    assert not result["candidates"]


def test_shadowed_go_numeric_name_is_not_a_pure_cast():
    _, _, result = build('''package sample
import "testing"
func uint(value int) int { events = append(events, value); return value }
var events []int
func accepts(value int) bool { return value < 4 }
func TestValue(t *testing.T) { if !accepts(uint(2)) { t.Fatal("bad") } }
''', "go", "sample_test.go")
    assert not result["candidates"]


def test_only_argument_participating_in_guard_is_changed():
    _, _, result = build('''def accepts(value: int, decoration: int):
    return value < 4
def test_value():
    assert accepts(2, 91) is True
''')
    assert result["candidates"]
    assert {c["edits"][0]["before"] for c in result["candidates"]} == {"2"}


def test_string_comparison_does_not_start_numeric_search():
    _, _, result = build('''def accepts(value: str):
    return value < "z"
def test_value():
    label = "a"
    assert accepts(label) is True
''')
    assert not result["candidates"]


def test_unsigned_zero_does_not_offer_negative_neighbour():
    _, _, result = build('''package sample
import "testing"
type Stamp uint64
func accepts(value Stamp) bool { return value < external.Load() }
func TestValue(t *testing.T) { if !accepts(0) { t.Fatal("bad") } }
''', "go", "sample_test.go")
    assert replacements(result) == {"(0) + 1"}


def test_exact_boundary_candidates_are_fair_and_deterministic():
    code = '''def accepts(value: int):
    return value < 4
def test_one():
    assert accepts(1) is True
def test_two():
    assert accepts(2) is True
'''
    corpus, frontend, result = build(code, budget=ScalarBudget(max_candidates=2))
    assert len({c["base_test_id"] for c in result["candidates"]}) == 2
    assert result == generate_scalar_cells(corpus, frontend, budget=ScalarBudget(max_candidates=2))
    assert result["counts"]["candidate_budget_exhausted"]


def test_typescript_alias_is_source_type_evidence():
    _, _, result = build('''type Count = number;
function accepts(value: Count): boolean { return value < upper.read(); }
test("value", () => { const n = 8; expect(accepts(n + 1)).toBe(true); });
''', "typescript", "sample.test.ts")
    assert replacements(result) == {"(n + 1) - 1", "(n + 1) + 1"}
    assert result["candidates"][0]["relation"]["numeric_type"]["aliases"][0]["name"] == "Count"


def test_argument_expression_neighbour_executes_once_and_preserves_ast():
    _, _, result = build('''def accepts(value: int):
    return value < meter.read()
def test_value():
    seq = 8
    assert accepts(seq + 1) is True
''')
    for candidate in result["candidates"]:
        after = candidate["edits"][0]["after"]
        expression = ast.parse(after, mode="eval").body
        assert isinstance(expression, ast.BinOp)
        assert ast.dump(expression.left) == ast.dump(ast.parse("seq + 1", mode="eval").body)
        assert eval(compile(ast.Expression(expression), "<test>", "eval"), {"seq": 8}) in {8, 10}


def test_budgets_are_bounded():
    with pytest.raises(ValueError):
        ScalarBudget(max_paths=0)
    with pytest.raises(ValueError):
        ScalarBudget(boundary_offsets=(-2, 2))


@pytest.mark.parametrize('decl,parameter,setup,condition', [
    ('type Record struct {}', '*Record', 'value := &Record{}', 'value != nil'),
    ('type Record [16]byte', 'Record', 'value := Record{}', 'value == Record{}'),
    ('type Record map[string]int', 'Record', 'value := Record{}', 'value != nil'),
])
def test_pointer_array_and_map_equality_are_not_integer_boundaries(decl, parameter, setup, condition):
    _, _, result = build(f'''package sample
import "testing"
{decl}
func accepts(value {parameter}) bool {{ return {condition} }}
func TestValue(t *testing.T) {{ {setup}; if !accepts(value) {{ t.Fatal("bad") }} }}
''', 'go', 'sample_test.go')
    assert not result['candidates']
    assert result['counts']['skipped']['non_integer_formals']


def test_untyped_object_identity_is_not_a_numeric_domain_premise():
    _, _, result = build('''def accepts(value): return value != None
class Record: pass
def test_value():
    value = Record()
    assert accepts(value)
''')
    assert not result['candidates']
    assert result['counts']['skipped']['numeric_actual_domain_unknown']
