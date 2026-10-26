"""Independent expected-template toys; no repository case data."""
import copy
import unittest

from anchor_retrieval.syntax import Source
from prototypes.test_action_and_oracle_transfer.oracle import Limits, OracleError, decode_value
from prototypes.test_action_and_oracle_transfer.expected_templates import extract_template, render_template


def source(expression, language):
    before, after = {
        "python": ("# 中文 byte offset\nexpected = ", "\n"),
        "typescript": ("// 中文 byte offset\nconst expected = ", ";\n"),
        "go": ("package toy\n// 中文 byte offset\nvar expected = ", "\n"),
    }[language]
    code = before + expression + after
    src = Source("independent_toy." + language, code, language)
    span = {"start_byte": len(before.encode()), "end_byte": len((before + expression).encode())}
    return src, span


def template(expression, language="python", **kwargs):
    return extract_template(*source(expression, language), **kwargs)


def vector(item):
    return [decode_value(hole["value"]) for hole in item["holes"]]


class ExpectedTemplateToys(unittest.TestCase):
    def test_python_constructor_keys_bindings_signs_and_unknowns(self):
        text = 'Box(name="中文", n=-3, payload={"fixed": [1, 2]}, same=bound, index=other[0], unknown=base + 7, nested=f(8), empty=[])'
        item = template(text)
        self.assertEqual(vector(item), ["中文", -3, 1, 2, 8])
        rendered = render_template(item, ["中文新", -5, 6, 9, 10], "python")
        self.assertEqual(rendered, "Box(name='中文新', n=-5, payload={\"fixed\": [6, 9]}, same=bound, index=other[0], unknown=base + 7, nested=f(10), empty=[])")
        for hole in item["holes"]:
            self.assertNotIn(item["text"].encode()[hole["start_byte"]:hole["end_byte"]], [b"fixed", b"bound", b"0", b"7"])
        self.assertIn(b"-3", [item["text"].encode()[h["start_byte"]:h["end_byte"]] for h in item["holes"]])

    def test_python_scalar_types_and_concatenated_strings(self):
        item = template('Box(b"ab", True, None, 1.25, "a" "b", f"fixed{7}")')
        self.assertEqual(vector(item), [b"ab", True, None, 1.25, "ab"])
        self.assertEqual(render_template(item, [b"cd", False, None, 2.5, "xy"], "python"),
                         'Box(b\'cd\', False, None, 2.5, \'xy\', f"fixed{7}")')

    def test_typescript_object_and_computed_keys_remain_fixed(self):
        item = template('new Box({key: -3, ["fixed"]: [1, 2], [f(17)]: true, bound, other: x[0], empty: {}, x: 3 as number})', "typescript")
        self.assertEqual(vector(item), [-3, 1, 2, True, 3])
        self.assertEqual(render_template(item, [-4, 5, 6, False, 7], "typescript"),
                         'new Box({key: -4, ["fixed"]: [5, 6], [f(17)]: false, bound, other: x[0], empty: {}, x: 7 as number})')

    def test_go_named_struct_alias_map_and_array_keys_remain_fixed(self):
        text = '&Thing{Name: "x", N: -3, Values: []int{1, 2}, Metadata: Alias{"fixed": 4}, X: known["key"], Y: uint64(7), Sequence: [5]int{1: 2, 3: 4}}'
        item = template(text, "go")
        self.assertEqual(vector(item), ["x", -3, 1, 2, 4, 7, 2, 4])
        self.assertEqual(render_template(item, ["y", -4, 5, 6, 8, 9, 10, 11], "go"),
                         '&Thing{Name: "y", N: -4, Values: []int{5, 6}, Metadata: Alias{"fixed": 8}, X: known["key"], Y: uint64(9), Sequence: [5]int{1: 10, 3: 11}}')

    def test_go_uint64_literal_and_raw_string(self):
        item = template('T{N: uint64(18446744073709551615), Text: `raw\\text`}', "go")
        self.assertEqual(vector(item), [18446744073709551615, "raw\\text"])
        rendered = render_template(item, vector(item), "go")
        self.assertIn("uint64(18446744073709551615)", rendered)
        self.assertIn('Text: "raw\\\\text"', rendered)

    def test_unique_hole_compatibility(self):
        item = template('Box(value=3, key=other[0])', min_holes=1)
        self.assertEqual(vector(item), [3])
        self.assertEqual(render_template(item, [4], "python"), 'Box(value=4, key=other[0])')
        with self.assertRaises(OracleError):
            template('Box(value=3, key=other[0])')
        with self.assertRaises(OracleError):
            template('Box(key=other[0])', min_holes=1)

    def test_scalar_and_control_roots_rejected(self):
        for expression in ['1', '-1', 'other[0]', 'x + 1', 'x if flag else 1']:
            with self.subTest(expression=expression), self.assertRaises(OracleError):
                template(expression, min_holes=1)

    def test_unsupported_text_is_fixed_and_never_scanned_for_literals(self):
        for language, expression in [
            ("python", 'Box(1, 2, f"inside{88}", seq[99], unknown + 77, *values)'),
            ("typescript", 'Box(1, 2, `inside${88}`, seq[99], unknown + 77, ...values)'),
            ("go", 'Box(1, 2, seq[99], unknown + 77)'),
        ]:
            with self.subTest(language=language):
                item = template(expression, language)
                self.assertEqual(vector(item), [1, 2])

    def test_exact_arity_and_types(self):
        item = template('Box(1, True, None, 2.0, "x", b"y")')
        for values in [[1], {"$tuple": vector(item)}, [True, True, None, 2.0, "x", b"y"],
                       [1, 1, None, 2.0, "x", b"y"], [1, True, None, 2, "x", b"y"],
                       [1, True, None, 2.0, ["x"], b"y"]]:
            with self.subTest(values=values), self.assertRaises(OracleError):
                render_template(item, values, "python")
        self.assertEqual(render_template(item, tuple(vector(item)), "python"), "Box(1, True, None, 2.0, 'x', b'y')")

    def test_overlap_out_of_bounds_malformed_and_wrong_original_rejected(self):
        item = template('Box(1, 2)')
        changes = [
            lambda t: t["holes"][1].update(start_byte=t["holes"][0]["start_byte"]),
            lambda t: t["holes"][1].update(end_byte=999),
            lambda t: t["holes"][0].update(value=9),
            lambda t: t["holes"][0].update(value_type="bool"),
            lambda t: t.update(language="go"),
        ]
        for change in changes:
            bad = copy.deepcopy(item)
            change(bad)
            with self.assertRaises(OracleError):
                render_template(bad, [1, 2], "python")

    def test_extraction_and_emission_budgets(self):
        with self.assertRaises(OracleError):
            template('Box(1, 2, 3)', max_holes=2)
        with self.assertRaises(OracleError):
            template('Box([[[[1]]]], 2)', limits=Limits(depth=2))
        with self.assertRaises(OracleError):
            template('Box(1, 2)', limits=Limits(expression_nodes=2))
        item = template('Box("x", "y")')
        with self.assertRaises(OracleError):
            render_template(item, ["long" * 100, "x"], "python", limits=Limits(expression_bytes=80))

    def test_partial_spans_and_syntax_errors_rejected(self):
        src, span = source('Box(1, 2)', "python")
        with self.assertRaises(OracleError):
            extract_template(src, (span["start_byte"] + 2, span["end_byte"]))
        with self.assertRaises(OracleError):
            template('Box(1, 2,,)')


if __name__ == "__main__":
    unittest.main(verbosity=2)
