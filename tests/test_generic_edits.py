from generic_composition.edits import LiteralEdit, encode_literal, learn_literal_edits, tokens


def test_literal_context_is_learned_from_examples_and_transported():
    rules = learn_literal_edits("item[12,4]", "item[12,4,7]")
    assert len(rules) == 1
    assert rules[0].apply("other[23,5]") == "other[23,5,7]"
    assert rules[0].apply("other(23,5)") is None
    assert LiteralEdit.from_dict(rules[0].as_dict()) == rules[0]


def test_repeated_carrier_holes_remain_correlated():
    rule = learn_literal_edits("same[12,12]", "same[12,12,7]")[0]
    assert rule.apply("different[8,8]") == "different[8,8,7]"
    assert rule.apply("different[8,9]") is None


def test_numeric_offset_is_explicit_hypothesis_not_an_input_contract():
    rules = learn_literal_edits("cell[4,2]", "cell[4,3]")
    fixed = next(x for x in rules if x.mode == "literal")
    offset = next(x for x in rules if x.mode == "offset")
    assert fixed.apply("box[8,5]") is None
    assert offset.apply("box[8,5]") == "box[8,6]"
    assert fixed.apply("cell[4,2]") == offset.apply("cell[4,2]") == "cell[4,3]"


def test_trivia_unicode_and_language_encoding_are_preserved():
    value = "_word α\n\t[12]\x1b"
    assert "".join(tokens(value)) == value
    import ast
    assert ast.literal_eval(encode_literal(value, "python")) == value
    assert encode_literal("a\nb", "go", "`old`") == "`a\nb`"


def test_no_unrelated_whole_string_replacement_or_unbounded_diff():
    assert not learn_literal_edits("red", "blue")
    assert not learn_literal_edits("[" + "1," * 300 + "]", "[x]")
