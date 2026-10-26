cd /app && python - <<'EOF'
path='/tmp/test_spec.py'
s=open(path).read()
s = s.replace('''assert r.value == Outer(Inner(x=1), 5)
assert r.structured_fields == frozenset({"z"})
assert r.failed_fields == frozenset({"inner"})
assert r.error_map["inner"] is not None''', '''assert r.value == Outer(Inner(x=1), 5)
assert r.structured_fields == frozenset({"z"})
assert r.failed_fields == frozenset({"inner"})''')
s = s.replace('''assert r.value == Complete(1, "x") and not r.is_complete
assert r.failed_fields == frozenset({"b"})
assert r.errors is not None''', '''assert r.value == Complete(1, "x") and not r.is_complete
assert r.failed_fields == frozenset({"b"})
assert r.errors is not None  # due to ForbiddenExtraKeysError''')
s = s.replace('''r = cn.partial_structure({"a": "bad"}, Complete)
print("nodetail:", r.errors, r.error_map)
assert r.errors is not None''', '''r = cn.partial_structure({"a": "bad"}, Complete)
print("nodetail:", r.errors, r.error_map)
assert r.errors is not None
assert r.error_map == {"a": r.errors}''')
open(path,'w').write(s)
EOF
cd /app && python /tmp/test_spec.py 2>&1 | tail -20