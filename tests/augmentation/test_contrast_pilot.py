from augmentation.contrast_pilot import Source, contrasts, expression_inventory, formula, consistent, walk, operator


def parse(code, language="typescript"):
    source = Source("subject.ts", code, language)
    nodes = [n for n in walk(source.root) if operator(source, n) in {"||", "&&", "and", "or"}]
    atoms = []
    tree = formula(source, nodes[0], atoms)
    return tree, atoms


def test_influence_and_masking_are_different():
    tree, atoms = parse("const out = fault !== null || old.flag || incoming.flag")
    rows = contrasts(tree, atoms)
    assert len(rows) == 3
    first = rows[0]
    assert first["independent_influence"] == {
        "before": [False, False, False], "after": [True, False, False],
        "truth_before": False, "truth_after": True}
    assert first["masked_influence"]["truth_before"] == first["masked_influence"]["truth_after"]


def test_impossible_same_access_assignments_are_rejected():
    tree, atoms = parse("const out = option === 'a' && option === 'b'")
    assert not consistent(atoms, (True, True))
    assert all(r["independent_influence"] is None for r in contrasts(tree, atoms))


def test_no_subject_call_is_interpreted_or_claimed_supported():
    source = Source("subject.ts", "const out = unsafe() || flag", "typescript")
    rows, unsupported = expression_inventory([source], [{"path": source.path, "line": 1, "end_line": 1}], {source.path: {1}})
    assert rows == []
    assert unsupported[0]["reason"] == "opaque_or_non_boolean_operation"


def test_large_expression_is_unsupported_not_silently_truncated():
    source = Source("subject.ts", "const out = a || b || c || d || e || f || g", "typescript")
    rows, unsupported = expression_inventory([source], [{"path": source.path, "line": 1, "end_line": 1}], {})
    assert rows == []
    assert unsupported[0]["reason"] == "operand_count_outside_2_to_6"


def test_python_conjunction():
    tree, atoms = parse("result = left and right", "python")
    assert contrasts(tree, atoms)[0]["independent_influence"]["before"] == [False, True]


def test_no_unseen_source_enters_expression_inventory():
    source = Source("subject.ts", "const out = a || b\nconst other = c || d", "typescript")
    rows, _ = expression_inventory([source], [{"path": source.path, "line": 1, "end_line": 1}], {})
    assert len(rows) == 1
    assert rows[0]["expression"] == "a || b"
