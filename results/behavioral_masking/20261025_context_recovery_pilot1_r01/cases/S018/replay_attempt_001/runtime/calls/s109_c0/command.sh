cd /app && python - <<'EOF'
path = 'tests/unit/core/test_nosec.py'
src = open(path).read()

replacements = [
    ('self.assertIsNone(nosec.combine_suppressions([nosec.Suppression.none()]))',
     'self.assertIsNone(\n            nosec.combine_suppressions([nosec.Suppression.none()])\n        )'),
    ('self.assertTrue(nosec._resolve_selector("", self.ENABLED, "nosec").is_blanket)',
     'self.assertTrue(\n            nosec._resolve_selector("", self.ENABLED, "nosec").is_blanket\n        )'),
    ('self.assertTrue(nosec._resolve_selector("all", self.ENABLED, "nosec").is_blanket)',
     'self.assertTrue(\n            nosec._resolve_selector("all", self.ENABLED, "nosec").is_blanket\n        )'),
    ('suppression = nosec._resolve_selector("B602 B607", self.ENABLED, "nosec")',
     'suppression = nosec._resolve_selector(\n            "B602 B607", self.ENABLED, "nosec"\n        )'),
    ('suppression = nosec._resolve_selector("B602, B607", self.ENABLED, "nosec")',
     'suppression = nosec._resolve_selector(\n            "B602, B607", self.ENABLED, "nosec"\n        )'),
    ('suppression = nosec._resolve_selector("B602 | B607", self.ENABLED, "nosec")',
     'suppression = nosec._resolve_selector(\n            "B602 | B607", self.ENABLED, "nosec"\n        )'),
    ('self.assertEqual({"B601", "B602", "B603", "B607", "B608"}, suppression.tests)',
     'self.assertEqual(\n            {"B601", "B602", "B603", "B607", "B608"},\n            suppression.tests,\n        )'),
    ('suppression = nosec._resolve_selector("on the line", self.ENABLED, "nosec")',
     'suppression = nosec._resolve_selector(\n            "on the line", self.ENABLED, "nosec"\n        )'),
    ('suppression = nosec._resolve_selector("on the line", self.ENABLED, "begin")',
     'suppression = nosec._resolve_selector(\n            "on the line", self.ENABLED, "begin"\n        )'),
    ('directives = nosec.parse_directives("# nosec-begin B602", 1, self.ENABLED)',
     'directives = nosec.parse_directives(\n            "# nosec-begin B602", 1, self.ENABLED\n        )'),
    ('directives = nosec.parse_directives("# NOSEC-BEGIN B602", 1, self.ENABLED)',
     'directives = nosec.parse_directives(\n            "# NOSEC-BEGIN B602", 1, self.ENABLED\n        )'),
    ('directives = nosec.parse_directives("# nosec-NEXT-LINE B602", 1, self.ENABLED)',
     'directives = nosec.parse_directives(\n            "# nosec-NEXT-LINE B602", 1, self.ENABLED\n        )'),
]

for old, new in replacements:
    if old not in src:
        print("MISSING:", old[:60])
    src = src.replace(old, new)

# Fix E303: two blank lines between methods within class (lines 267-269)
src = src.replace('''        self.assertNotIn(2, nosec_lines)


    def test_next_line_combined_with_region(self):''', '''        self.assertNotIn(2, nosec_lines)

    def test_next_line_combined_with_region(self):''')

# Remove trailing extra blank lines
src = src.rstrip() + '\n'
open(path, 'w').write(src)
print("test file fixed")
EOF
python -m flake8 tests/unit/core/test_nosec.py 2>&1 | head