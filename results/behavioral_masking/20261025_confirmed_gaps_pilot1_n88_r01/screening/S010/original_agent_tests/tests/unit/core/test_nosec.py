#
# SPDX-License-Identifier: Apache-2.0
import testtools

from bandit.core import nosec


class NosecSelectorTests(testtools.TestCase):
    def assertSuppression(self, selector, expected):
        """Assert parse_selector returns the expected suppression value."""
        result = nosec.parse_selector(selector)
        if expected is None:
            self.assertIsNone(result)
        elif expected == "all":
            self.assertEqual(set(), result)
        else:
            self.assertEqual(set(expected), result)

    def test_empty_selector_is_blanket(self):
        self.assertSuppression("", "all")
        self.assertSuppression(None, "all")

    def test_all_token_is_blanket(self):
        self.assertSuppression("all", "all")

    def test_none_token_is_no_suppression(self):
        self.assertSuppression("none", None)

    def test_single_test_id(self):
        self.assertSuppression("B602", ["B602"])

    def test_multiple_test_ids_space_separated(self):
        self.assertSuppression("B602 B607", ["B602", "B607"])

    def test_multiple_test_ids_comma_separated(self):
        self.assertSuppression("B602, B607", ["B602", "B607"])

    def test_union_operator(self):
        self.assertSuppression("B602 | B607", ["B602", "B607"])

    def test_intersection_operator(self):
        self.assertSuppression("B602 & B607", None)
        self.assertSuppression("B60* & B602", ["B602"])

    def test_difference_operator(self):
        self.assertSuppression("B602 - B607", ["B602"])
        self.assertSuppression("B602 - B602", None)

    def test_negation_operator(self):
        result = nosec.parse_selector("!B602")
        self.assertIsNotNone(result)
        self.assertNotEqual(set(), result)
        self.assertIn("B607", result)
        self.assertNotIn("B602", result)

    def test_glob_wildcard(self):
        result = nosec.parse_selector("B60*")
        self.assertIn("B602", result)
        self.assertIn("B607", result)
        self.assertNotIn("B101", result)

    def test_parentheses_grouping(self):
        self.assertSuppression("(B602 | B607) & B602", ["B602"])
        self.assertSuppression("(B602 | B607) - B602", ["B607"])

    def test_test_name(self):
        self.assertSuppression(
            "subprocess_popen_with_shell_equals_true", ["B602"]
        )

    def test_unrecognized_text_is_blanket(self):
        # Legacy behavior: a selector with no recognized tests suppresses
        # everything.
        self.assertSuppression("TODO", "all")
        self.assertSuppression("(on the line)", "all")

    def test_negation_of_all_is_no_suppression(self):
        self.assertSuppression("!all", None)

    def test_negation_of_none_is_blanket(self):
        self.assertSuppression("!none", "all")

    def test_invalid_expression_falls_back_to_union(self):
        # A trailing operator cannot be parsed; it falls back to a plain
        # union of the tokens.
        self.assertSuppression("B602 |", ["B602"])
        self.assertSuppression("B602 B607 (", ["B602", "B607"])

    def test_combine(self):
        self.assertIsNone(nosec.combine([None, None]))
        self.assertEqual(set(), nosec.combine([None, set()]))
        self.assertEqual(
            {"B602", "B607"}, nosec.combine([{"B602"}, {"B607"}])
        )
        # Blanket dominates.
        self.assertEqual(set(), nosec.combine([{"B602"}, set()]))
