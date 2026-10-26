cd /app && python3 - <<'EOF'
path = '/tmp/test_safe.py'
src = open(path).read()
old = '''    before_schema3 = db3.schema
    db3.enable_safe_import()
    db3.add_import_invariant("t", "COUNT(*) < 2")
    result3 = db3.safe_bulk_insert("t", [{"id": 2, "name": "b"}], pk="id")
    assert result3["success"] is False
    assert db3.schema == before_schema3, (before_schema3, db3.schema)
    assert db3.table_names() == ["t"]
    assert set(db3.triggers_dict.keys()) == {"trg"}
    assert db3["t"].indexes[0].name  # index still there'''
new = '''    db3.enable_safe_import()
    db3.add_import_invariant("t", "COUNT(*) < 2")
    before_schema3 = db3.schema
    before_rows3 = list(db3["t"].rows)
    result3 = db3.safe_bulk_insert("t", [{"id": 2, "name": "b"}], pk="id")
    assert result3["success"] is False
    assert db3.schema == before_schema3, (before_schema3, db3.schema)
    assert db3.table_names() == ["t", "_import_invariants"]
    assert set(db3.triggers_dict.keys()) == {"trg"}
    assert db3["t"].indexes[0].name  # index still there
    assert list(db3["t"].rows) == before_rows3
    assert [c.name for c in db3["t"].columns] == ["id", "name"]'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("updated")
EOF
PYTHONPATH=/app python3 /tmp/test_safe.py