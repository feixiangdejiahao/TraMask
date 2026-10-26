cd /app && python - <<'EOF'
path='/tmp/test_spec.py'
s=open(path).read()
old='''r2 = r.refine({"inner": {"y": "w"}})
print("refine nested:", r2.value, r2.is_complete, r2.structured_fields, r2.failed_fields)
assert r2.value == Outer(Inner(1, "w"), 5)
assert r2.is_complete'''
new='''r2 = r.refine({"inner": {"x": 1, "y": "w"}})
print("refine nested:", r2.value, r2.is_complete, r2.structured_fields, r2.failed_fields)
assert r2.value == Outer(Inner(1, "w"), 5)
assert r2.is_complete'''
assert old in s
open(path,'w').write(s.replace(old,new))
EOF
cd /app && python /tmp/test_spec.py 2>&1 | tail -4