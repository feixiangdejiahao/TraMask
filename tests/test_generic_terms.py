"""Mechanical syntax properties, using independent examples only."""
from dataclasses import FrozenInstanceError

import pytest

from anchor_retrieval.syntax import Source, walk
from generic_composition.terms import (
    AntiUnification, BindingInterface, BudgetExceeded, CaptureError, Hole, Term,
    anti_unify, at, check_capture, context_at, from_source, match, render,
    replace_at, substitute, subterms,
)


def atom(value):
    return Term("integer", str(value))


def call(*arguments):
    return Term("call", None, tuple(arguments))


def test_repeated_mismatches_are_one_correlated_hole_and_reconstruct():
    left, right = call(atom(1), atom(1)), call(atom(2), atom(2))
    result = anti_unify(left, right)
    pattern, a, b = result
    assert isinstance(result, AntiUnification)
    assert pattern == call(Hole("integer", 0), Hole("integer", 0))
    assert substitute(pattern, a) == left
    assert substitute(pattern, b) == right
    assert match(pattern, call(atom(3), atom(3))) == {Hole("integer", 0): atom(3)}
    assert match(pattern, call(atom(3), atom(4))) is None


def test_distinct_pairs_do_not_merge_just_because_one_side_matches():
    result = anti_unify(call(atom(1), atom(1)), call(atom(2), atom(3)))
    assert len(result.left_subst) == 2
    assert result.pattern.children[0] != result.pattern.children[1]


def test_atom_types_are_preserved_despite_python_numeric_equality():
    boolean, integer = Term("literal", True), Term("literal", 1)
    assert boolean != integer
    result = anti_unify(boolean, integer)
    assert isinstance(result.pattern, Hole)
    assert render(substitute(result.pattern, result.left_subst)) == "True"
    assert render(substitute(result.pattern, result.right_subst)) == "1"


def test_shared_structure_is_preserved_and_hole_numbering_is_deterministic():
    left = call(Term("identifier", "keep"), call(atom(1), Term("string", "'key'")))
    right = call(Term("identifier", "keep"), call(atom(4), Term("string", "'key'")))
    assert anti_unify(left, right) == anti_unify(left, right)
    result = anti_unify(left, right)
    assert result.pattern.children[0] == left.children[0]
    assert substitute(result.pattern, result.right_subst) == right


def test_external_sorts_are_required_to_treat_different_kinds_as_same_class():
    left, right = Term("integer", "1"), Term("identifier", "value")
    assert anti_unify(left, right).pattern == Hole("any", 0)
    sort_of = lambda node: "expression" if node.kind in {"integer", "identifier"} else node.kind
    pattern = anti_unify(left, right, sort_of=sort_of).pattern
    assert pattern == Hole("expression", 0)
    assert match(pattern, right) is None
    assert match(pattern, right, sort_of=sort_of) == {pattern: right}
    assert match(pattern, Term("comment", "# no"), sort_of=sort_of) is None


@pytest.mark.parametrize("language,filename,code", [
    ("python", "sample.py", "# hello\nx = {'π': 1}  # keep punctuation\nassert x['π'] == 1\n"),
    ("go", "sample.go", 'package demo\nfunc f() { x := []int{1, 2}; _ = x /* end */ }\n'),
    ("typescript", "sample.ts", 'const x = {name: "雪", value: 2};\ncheck(x.value === 2);\n'),
])
def test_source_roundtrip_keeps_all_tokens_trivia_and_utf8_spans(language, filename, code):
    source = Source(filename, code, language)
    converted = from_source(source)
    assert render(converted.term) == code
    for path, term in subterms(converted.term):
        span = converted.spans[path]
        assert render(term) == source.data[span.start_byte:span.end_byte].decode()


def test_position_normalization_changes_only_explicit_binding_tokens():
    code = 'entry = {"entry": 1}\nassert entry.entry == "entry"\n'
    source = Source("names.py", code, "python")
    identifiers = [n for n in walk(source.root) if n.type == "identifier" and source.text(n) == "entry"]
    # The caller supplies only the declaration and receiver, not the property.
    chosen = [identifiers[0], identifiers[1]]
    mapping = {(n.start_byte, n.end_byte): "binding0" for n in chosen}
    converted = from_source(source, normalization_map=mapping)
    assert render(converted.term) == 'binding0 = {"entry": 1}\nassert binding0.entry == "entry"\n'
    assert converted.original_text == code
    with pytest.raises(ValueError, match="not leaf"):
        from_source(source, normalization_map={(0, len(code.encode())): "wrong"})


def test_callback_normalization_and_source_metadata_do_not_affect_equality():
    a = from_source(Source("one.py", "first = 1", "python"),
                    normalize=lambda node, text: "binding0" if node.type == "identifier" else None)
    b = from_source(Source("two.py", "second = 1", "python"),
                    normalize=lambda node, text: "binding0" if node.type == "identifier" else None)
    assert a == b
    assert a.original_text != b.original_text
    assert a.spans != b.spans
    with pytest.raises(TypeError):
        a.spans[()] = b.spans[()]


def test_subtree_replacement_changes_one_occurrence_and_preserves_other_atoms():
    original = call(Term("identifier", "x"), Term("attribute", "x"), Term("string", '"x"'))
    changed = replace_at(original, (0,), Term("identifier", "renamed"))
    assert original.children[0].atom == "x"
    assert changed.children[1:] == original.children[1:]
    hole = Hole("identifier", "carrier")
    context = context_at(original, (0,), hole)
    assert substitute(context, {hole: at(original, (0,))}) == original
    assert [path for path, _ in subterms(original)] == [(), (0,), (1,), (2,)]
    with pytest.raises(IndexError):
        replace_at(original, (-1,), atom(3))


def test_capture_interface_rejects_both_directions_without_guessing_bindings():
    donor = BindingInterface(free={"outside"}, bound={"temporary"})
    check_capture(donor, available={"outside"}, surrounding_bound={"other"}, context_free={"value"})
    with pytest.raises(CaptureError, match="donor_capture"):
        check_capture(donor, available={"outside"}, surrounding_bound={"outside"})
    with pytest.raises(CaptureError, match="context_capture"):
        check_capture(donor, available={"outside"}, context_free={"temporary"})
    with pytest.raises(CaptureError, match="missing"):
        check_capture(donor)


def test_budget_failures_are_explicit_not_partial_generalizations():
    with pytest.raises(BudgetExceeded):
        anti_unify(call(atom(1), atom(2)), call(atom(3), atom(4)), max_holes=1)
    with pytest.raises(BudgetExceeded):
        anti_unify(call(atom(1)), call(atom(2)), max_nodes=1)
    with pytest.raises(BudgetExceeded):
        from_source(Source("tiny.py", "x = 1", "python"), max_nodes=2)
    with pytest.raises(BudgetExceeded):
        list(subterms(call(call(atom(1))), max_depth=1))
    hole = Hole("any", 0)
    with pytest.raises(BudgetExceeded):
        substitute(call(hole, hole), {hole: call(atom(1), atom(2))}, max_nodes=5)


def test_substitution_is_simultaneous_and_missing_holes_are_explicit():
    first, second = Hole("any", 0), Hole("any", 1)
    assert substitute(first, {first: second, second: atom(3)}) == second
    assert substitute(call(first), {}, strict=False) == call(first)
    with pytest.raises(KeyError):
        substitute(first, {})
    with pytest.raises(ValueError, match="unbound"):
        render(call(first))
    with pytest.raises(ValueError, match="ground"):
        anti_unify(call(first), call(atom(1)))


def test_terms_are_immutable_and_nonshared_mutable_children_are_copied():
    children = [atom(1)]
    term = Term("call", None, children)
    children.append(atom(2))
    assert term.children == (atom(1),)
    with pytest.raises(FrozenInstanceError):
        term.atom = "changed"
    with pytest.raises(TypeError):
        Term("mutable", [])
