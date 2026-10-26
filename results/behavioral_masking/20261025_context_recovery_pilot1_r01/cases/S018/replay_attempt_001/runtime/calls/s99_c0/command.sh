cd /app && python - <<'EOF'
path = 'tests/unit/core/test_nosec.py'
src = open(path).read()
extra = '''
    def test_next_line_decorated_function(self):
        source = (
            "# nosec-next-line\\n"
            "@decorator\\n"
            "def foo():\\n"
            "    bar()\\n"
        )
        nosec_lines = self._build(source)
        self.assertIn(3, nosec_lines)
        self.assertIn(4, nosec_lines)
'''
src = src.rstrip() + '\n' + extra + '\n'
open(path, 'w').write(src)
print("added")
EOF
python -m testtools.run tests.unit.core.test_nosec 2>&1 | tail -6