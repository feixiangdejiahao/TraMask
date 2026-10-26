cd /app && python - <<'EOF'
path='/tmp/test_spec.py'
s=open(path).read()
# Update def case: errors None, error_map empty
old='''assert r.value == Def(1) and not r.is_complete
assert r.failed_fields == frozenset({"b"}) and r.structured_fields == frozenset({"a"})
assert r.errors is not None and "b" in r.error_map'''
new='''assert r.value == Def(1) and not r.is_complete
assert r.failed_fields == frozenset({"b"}) and r.structured_fields == frozenset({"a"})
assert r.errors is None and r.error_map == {}'''
assert old in s
open(path,'w').write(s.replace(old,new))
EOF
cd /app && python /tmp/test_spec.py 2>&1 | tail -20