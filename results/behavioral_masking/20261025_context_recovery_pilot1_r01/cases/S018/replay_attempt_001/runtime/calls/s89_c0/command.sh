cd /app && python - <<'EOF'
path = 'tests/unit/core/test_nosec.py'
src = open(path).read()
old = '''    def test_next_line_skips_continuation(self):
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
new = '''    def test_next_line_skips_continuation(self):
        source = (
            "foo(\\n"
            "    # nosec-next-line\\n"
            "    bar,\\n"
            ")\\n"
            "baz()\\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(5, nosec_lines)
        self.assertNotIn(3, nosec_lines)
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("updated")
EOF
python -m testtools.run tests.unit.core.test_nosec 2>&1 | tail -6