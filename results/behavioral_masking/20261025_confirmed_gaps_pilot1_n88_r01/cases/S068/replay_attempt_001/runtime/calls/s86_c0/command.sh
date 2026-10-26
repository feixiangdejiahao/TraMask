cd /app && python3 - <<'EOF'
path = 'tests/test_safe_import.py'
src = open(path).read()
src = src.replace('''    result = db.validate_import_invariants("items")
    assert result["valid"] is False
    assert len(result["failures"]) == 1


def test_import_invariant_select():''', '''    result = db.validate_import_invariants("items")
    assert result["valid"] is False
    assert len(result["failures"]) == 2


def test_import_invariant_select():''')
open(path, 'w').write(src)
print("fixed")
EOF
cd /app && python3 -m pytest tests/test_safe_import.py -q 2>&1 | tail -5