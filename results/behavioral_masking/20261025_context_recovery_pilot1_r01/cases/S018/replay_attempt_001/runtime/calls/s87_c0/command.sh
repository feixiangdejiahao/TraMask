cd /app && python - <<'EOF'
path = 'tests/unit/core/test_nosec.py'
src = open(path).read()
extra = '''

    def test_next_line_combined_with_region(self):
        source = (
            "# nosec-begin B607\\n"
            "# nosec-next-line B602\\n"
            "foo()\\n"
            "# nosec-end\\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(3, nosec_lines)
        self.assertEqual({"B602", "B607"}, nosec_lines[3].tests)

    def test_statement_wide_region_with_end_inside(self):
        source = (
            "foo(\\n"
            "    # nosec-begin\\n"
            "    bar,\\n"
            "    # nosec-end\\n"
            ")\\n"
        )
        nosec_lines = self._build(source)
        # The statement spans lines 1-5; the region covers line 3, so the
        # whole statement should be considered suppressed.
        self.assertIn(3, nosec_lines)
        self.assertTrue(nosec_lines[3].is_blanket)

    def test_next_line_skips_semicolon_and_ellipsis(self):
        source = (
            "# nosec-next-line\\n"
            ";\\n"
            "...\\n"
            "foo()\\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(4, nosec_lines)

    def test_next_line_skips_continuation(self):
        source = (
            "x = 1 + \\\\n"
            "# nosec-next-line\\n"
            "    2\\n"
            "foo()\\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(4, nosec_lines)
        self.assertNotIn(3, nosec_lines)
'''
# Insert before the final blank / end of class
idx = src.rstrip().rfind('\n')
src = src.rstrip() + '\n' + extra + '\n'
open(path, 'w').write(src)
print("appended")
EOF
python -m testtools.run tests.unit.core.test_nosec 2>&1 | tail -15