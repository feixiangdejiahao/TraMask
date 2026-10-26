cd /app && cat > tests/unit/core/test_nosec.py <<'PYEOF'
#
# SPDX-License-Identifier: Apache-2.0
import testtools

from bandit.core import nosec


class SuppressionTests(testtools.TestCase):
    def test_blanket(self):
        self.assertTrue(nosec.Suppression.blanket().is_blanket)
        self.assertFalse(nosec.Suppression.blanket().is_specific)
        self.assertFalse(nosec.Suppression.blanket().is_none)

    def test_none(self):
        suppression = nosec.Suppression.none()
        self.assertTrue(suppression.is_none)
        self.assertFalse(suppression.is_blanket)
        self.assertFalse(suppression.is_specific)
        self.assertFalse(bool(suppression))

    def test_specific(self):
        suppression = nosec.Suppression.specific(["B602"])
        self.assertTrue(suppression.is_specific)
        self.assertFalse(suppression.is_blanket)
        self.assertEqual({"B602"}, suppression.tests)

    def test_combine_blanket_dominates(self):
        combined = nosec.combine_suppressions(
            [
                nosec.Suppression.specific(["B602"]),
                nosec.Suppression.blanket(),
            ]
        )
        self.assertTrue(combined.is_blanket)

    def test_combine_specific_union(self):
        combined = nosec.combine_suppressions(
            [
                nosec.Suppression.specific(["B602"]),
                nosec.Suppression.specific(["B607"]),
            ]
        )
        self.assertEqual({"B602", "B607"}, combined.tests)

    def test_combine_none_ignored(self):
        combined = nosec.combine_suppressions(
            [nosec.Suppression.none(), nosec.Suppression.specific(["B602"])]
        )
        self.assertEqual({"B602"}, combined.tests)

    def test_combine_empty(self):
        self.assertIsNone(nosec.combine_suppressions([]))
        self.assertIsNone(nosec.combine_suppressions([nosec.Suppression.none()]))


class SelectorTests(testtools.TestCase):
    ENABLED = {"B601", "B602", "B603", "B607", "B608"}

    def _resolve(self, text):
        return nosec._evaluate(nosec._tokenize(text), self.ENABLED)

    def test_blank(self):
        self.assertTrue(nosec._resolve_selector("", self.ENABLED, "nosec").is_blanket)

    def test_all(self):
        self.assertTrue(nosec._resolve_selector("all", self.ENABLED, "nosec").is_blanket)

    def test_none(self):
        suppression = nosec._resolve_selector("none", self.ENABLED, "nosec")
        self.assertTrue(suppression.is_none)

    def test_single_id(self):
        suppression = nosec._resolve_selector("B602", self.ENABLED, "nosec")
        self.assertEqual({"B602"}, suppression.tests)

    def test_name(self):
        suppression = nosec._resolve_selector(
            "subprocess_popen_with_shell_equals_true", self.ENABLED, "nosec"
        )
        self.assertEqual({"B602"}, suppression.tests)

    def test_union_space(self):
        suppression = nosec._resolve_selector("B602 B607", self.ENABLED, "nosec")
        self.assertEqual({"B602", "B607"}, suppression.tests)

    def test_union_comma(self):
        suppression = nosec._resolve_selector("B602, B607", self.ENABLED, "nosec")
        self.assertEqual({"B602", "B607"}, suppression.tests)

    def test_union_pipe(self):
        suppression = nosec._resolve_selector("B602 | B607", self.ENABLED, "nosec")
        self.assertEqual({"B602", "B607"}, suppression.tests)

    def test_intersection(self):
        suppression = nosec._resolve_selector(
            "B60* & B602", self.ENABLED, "nosec"
        )
        self.assertEqual({"B602"}, suppression.tests)

    def test_difference(self):
        suppression = nosec._resolve_selector(
            "B60* - B602", self.ENABLED, "nosec"
        )
        self.assertEqual({"B601", "B603", "B607", "B608"}, suppression.tests)

    def test_negation(self):
        suppression = nosec._resolve_selector("!B602", self.ENABLED, "nosec")
        self.assertEqual(self.ENABLED - {"B602"}, suppression.tests)

    def test_glob(self):
        suppression = nosec._resolve_selector("B60*", self.ENABLED, "nosec")
        self.assertEqual({"B601", "B602", "B603", "B607", "B608"}, suppression.tests)

    def test_parenthesized(self):
        suppression = nosec._resolve_selector(
            "(B602 | B607) & !B607", self.ENABLED, "nosec"
        )
        self.assertEqual({"B602"}, suppression.tests)

    def test_fallback_union(self):
        suppression = nosec._resolve_selector(
            "B602 &", self.ENABLED, "nosec"
        )
        self.assertEqual({"B602"}, suppression.tests)

    def test_unknown_token_nosec_backwards_compat(self):
        # Historically `# nosec <unknown text>` was a blanket suppression.
        suppression = nosec._resolve_selector("on the line", self.ENABLED, "nosec")
        self.assertTrue(suppression.is_blanket)

    def test_unknown_token_begin_is_none(self):
        suppression = nosec._resolve_selector("on the line", self.ENABLED, "begin")
        self.assertTrue(suppression.is_none)

    def test_case_insensitive_all(self):
        suppression = nosec._resolve_selector("ALL", self.ENABLED, "nosec")
        self.assertTrue(suppression.is_blanket)


class DirectiveParseTests(testtools.TestCase):
    ENABLED = {"B602", "B607"}

    def test_plain_nosec(self):
        directives = nosec.parse_directives("# nosec B602", 1, self.ENABLED)
        self.assertEqual(1, len(directives))
        self.assertEqual("nosec", directives[0].type)
        self.assertEqual({"B602"}, directives[0].suppression.tests)

    def test_begin(self):
        directives = nosec.parse_directives("# nosec-begin B602", 1, self.ENABLED)
        self.assertEqual(1, len(directives))
        self.assertEqual("begin", directives[0].type)
        self.assertEqual({"B602"}, directives[0].suppression.tests)

    def test_end(self):
        directives = nosec.parse_directives(
            "# nosec-end extra text ignored", 1, self.ENABLED
        )
        self.assertEqual(1, len(directives))
        self.assertEqual("end", directives[0].type)

    def test_next_line(self):
        directives = nosec.parse_directives(
            "# nosec-next-line B602", 1, self.ENABLED
        )
        self.assertEqual(1, len(directives))
        self.assertEqual("next_line", directives[0].type)

    def test_case_insensitive_keywords(self):
        directives = nosec.parse_directives("# NOSEC-BEGIN B602", 1, self.ENABLED)
        self.assertEqual("begin", directives[0].type)
        directives = nosec.parse_directives("# nosec-NEXT-LINE B602", 1, self.ENABLED)
        self.assertEqual("next_line", directives[0].type)
        directives = nosec.parse_directives("# NOSEC-END", 1, self.ENABLED)
        self.assertEqual("end", directives[0].type)

    def test_multiple_directives_in_one_comment(self):
        directives = nosec.parse_directives(
            "# nosec-begin B602 # nosec-end", 1, self.ENABLED
        )
        self.assertEqual(2, len(directives))
        self.assertEqual("begin", directives[0].type)
        self.assertEqual("end", directives[1].type)

    def test_colon_selector(self):
        directives = nosec.parse_directives("# nosec: B602", 1, self.ENABLED)
        self.assertEqual({"B602"}, directives[0].suppression.tests)


class BuildNosecLinesTests(testtools.TestCase):
    ENABLED = {"B602", "B607"}

    def _build(self, source):
        return nosec.build_nosec_lines(source.encode(), self.ENABLED)

    def test_region(self):
        source = (
            "# nosec-begin\n"
            "foo()\n"
            "# nosec-end\n"
            "bar()\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(2, nosec_lines)
        self.assertTrue(nosec_lines[2].is_blanket)
        self.assertNotIn(3, nosec_lines)
        self.assertNotIn(4, nosec_lines)

    def test_region_not_retroactive(self):
        source = (
            "foo()\n"
            "# nosec-begin\n"
            "bar()\n"
        )
        nosec_lines = self._build(source)
        self.assertNotIn(1, nosec_lines)
        self.assertIn(3, nosec_lines)

    def test_auto_close_on_dedent(self):
        source = (
            "def f():\n"
            "    # nosec-begin\n"
            "    foo()\n"
            "bar()\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(3, nosec_lines)
        self.assertNotIn(4, nosec_lines)

    def test_blank_line_does_not_auto_close(self):
        source = (
            "def f():\n"
            "    # nosec-begin\n"
            "\n"
            "    foo()\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(4, nosec_lines)

    def test_next_line(self):
        source = (
            "# nosec-next-line\n"
            "\n"
            "# comment\n"
            "foo()\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(4, nosec_lines)
        self.assertTrue(nosec_lines[4].is_blanket)

    def test_next_line_grouping_only(self):
        source = (
            "# nosec-next-line\n"
            "(\n"
            "    foo()\n"
            ")\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(2, nosec_lines)
        self.assertIn(3, nosec_lines)
        self.assertIn(4, nosec_lines)

    def test_unmatched_end_does_nothing(self):
        source = "# nosec-end\nfoo()\n"
        nosec_lines = self._build(source)
        self.assertNotIn(2, nosec_lines)
PYEOF
python -m testtools.run tests.unit.core.test_nosec 2>&1 | tail -30