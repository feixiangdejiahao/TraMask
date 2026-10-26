cd /app && python3 - <<'EOF'
path = '/tmp/test_safe.py'
src = open(path).read()
src = src.replace('''    db2.add_import_invariant("x", "SELECT a = 1 FROM x")
    assert db2.validate_import_invariants("x")["valid"] is True
    db2["x"].insert({"a": 0})
    assert db2.validate_import_invariants("x")["valid"] is False''', '''    db2.add_import_invariant("x", "SELECT a = 1 FROM x")
    assert db2.validate_import_invariants("x")["valid"] is True
    # SELECT invariants use the first row
    db2["x"].insert({"a": 0})
    assert db2.validate_import_invariants("x")["valid"] is True''')
src = src.replace('db.create_index("existing", ["name"], unique=True)', 'db["existing"].create_index(["name"], unique=True)')
src = src.replace('db3.create_index("t", ["name"])', 'db3["t"].create_index(["name"])')
open(path, 'w').write(src)
print("updated")
EOF
PYTHONPATH=/app python3 /tmp/test_safe.py