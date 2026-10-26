cd /app && python - <<'EOF'
path = 'tests/functional/test_functional.py'
src = open(path).read()
anchor = '''    def test_nosec(self):
        expect = {
            "SEVERITY": {"UNDEFINED": 0, "LOW": 5, "MEDIUM": 0, "HIGH": 0},
            "CONFIDENCE": {"UNDEFINED": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 5},
        }
        self.check_example("nosec.py", expect)
'''
new = anchor + '''
    def test_nosec_directives(self):
        """Test `# nosec-begin`, `# nosec-end` and `# nosec-next-line`."""
        expect = {
            "SEVERITY": {"UNDEFINED": 0, "LOW": 5, "MEDIUM": 0, "HIGH": 0},
            "CONFIDENCE": {"UNDEFINED": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 5},
        }
        expect_stats = {
            "nosec": 6,
            "skipped_tests": 2,
        }
        self.check_example("nosec-directives.py", expect)
        self.check_metrics("nosec-directives.py", expect_stats)

    def test_ignore_nosec_directives(self):
        """Test --ignore-nosec ignores region and next-line directives."""
        expect = {
            "SEVERITY": {"UNDEFINED": 0, "LOW": 9, "MEDIUM": 0, "HIGH": 0},
            "CONFIDENCE": {"UNDEFINED": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 9},
        }
        self.check_example(
            "nosec-directives.py", expect, ignore_nosec=True
        )
'''
assert anchor in src
src = src.replace(anchor, new)
open(path, 'w').write(src)
print("added")
EOF
cd /app && python -m bandit --ignore-nosec -f json examples/nosec-directives.py 2>/dev/null | python -c "import json,sys; d=json.load(sys.stdin); print('metrics', d['metrics']['_totals']); [print(r['line_number'], r['test_id']) for r in d['results']]"