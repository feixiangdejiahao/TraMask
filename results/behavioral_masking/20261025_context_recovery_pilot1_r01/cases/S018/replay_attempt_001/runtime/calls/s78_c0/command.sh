cd /app && python - <<'EOF'
path = 'tests/functional/test_functional.py'
src = open(path).read()
old = '''        expect = {
            "SEVERITY": {"UNDEFINED": 0, "LOW": 9, "MEDIUM": 0, "HIGH": 0},
            "CONFIDENCE": {"UNDEFINED": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 9},
        }
        self.check_example(
            "nosec-directives.py", expect, ignore_nosec=True
        )'''
new = '''        expect = {
            "SEVERITY": {"UNDEFINED": 0, "LOW": 13, "MEDIUM": 0, "HIGH": 0},
            "CONFIDENCE": {"UNDEFINED": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 13},
        }
        self.check_example(
            "nosec-directives.py", expect, ignore_nosec=True
        )'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("fixed")
EOF
python -m testtools.run tests.functional.test_functional 2>&1 | tail -8