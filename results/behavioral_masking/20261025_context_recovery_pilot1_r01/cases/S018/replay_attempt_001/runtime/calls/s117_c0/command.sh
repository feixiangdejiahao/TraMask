cd /app && python - <<'EOF'
path = 'tests/unit/core/test_nosec.py'
src = open(path).read()
old = '''    def test_colon_selector(self):
        directives = nosec.parse_directives("# nosec: B602", 1, self.ENABLED)


    def test_partial_keyword_not_directive(self):
        directives = nosec.parse_directives(
            "# nosec-beginning", 1, self.ENABLED
        )
        self.assertEqual([], directives)
        directives = nosec.parse_directives(
            "# nosec-endpoint", 1, self.ENABLED
        )
        self.assertEqual([], directives)
'''
new = '''    def test_colon_selector(self):
        directives = nosec.parse_directives("# nosec: B602", 1, self.ENABLED)
        self.assertEqual({"B602"}, directives[0].suppression.tests)

    def test_partial_keyword_not_directive(self):
        directives = nosec.parse_directives(
            "# nosec-beginning", 1, self.ENABLED
        )
        self.assertEqual([], directives)
        directives = nosec.parse_directives(
            "# nosec-endpoint", 1, self.ENABLED
        )
        self.assertEqual([], directives)
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("fixed")
EOF
python -m flake8 tests/unit/core/test_nosec.py && python -m testtools.run tests.unit.core.test_nosec 2>&1 | tail -4