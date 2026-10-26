cd /app && python - <<'EOF'
path = 'tests/unit/core/test_nosec.py'
src = open(path).read()
src = src.replace(
    '    ENABLED = {"B601", "B602", "B603", "B607", "B608"}',
    '    ENABLED = {"B101", "B601", "B602", "B603", "B607", "B608"}',
)
src = src.replace(
    '        self.assertEqual({"B601", "B603", "B607", "B608"}, suppression.tests)',
    '        self.assertEqual({"B601", "B603", "B607", "B608"}, suppression.tests)',
)
src = src.replace(
    '        self.assertEqual(self.ENABLED - {"B602"}, suppression.tests)',
    '        self.assertEqual(self.ENABLED - {"B602"}, suppression.tests)',
)
# test_glob now B60* doesn't match B101
open(path, 'w').write(src)
print("updated")
EOF
python -m testtools.run tests.unit.core.test_nosec 2>&1 | tail -6