cd /app && python - <<'EOF'
path = 'tests/unit/core/test_nosec.py'
src = open(path).read()
extra = '''
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
# Insert into DirectiveParseTests before its final method? We'll append at end of class.
# Simpler: append to end of file; but class structure: append before BuildNosecLinesTests class? 
# We'll insert right before the last closing of DirectiveParseTests by finding the marker of the next class.
marker = 'class BuildNosecLinesTests'
idx = src.index(marker)
src = src[:idx] + extra + '\n\n' + src[idx:]
open(path, 'w').write(src)
print("added")
EOF
python -m flake8 tests/unit/core/test_nosec.py && python -m testtools.run tests.unit.core.test_nosec 2>&1 | tail -5