cd /app && python - <<'EOF'
path='src/cattrs/partial.py'
s=open(path).read()
old='''            else:
                value = converter.structure(obj[key], t)
                kwargs[kwarg_key] = value
                structured_fields.add(name)
'''
new='''            else:
                value = converter._structure_attribute(a, obj[key])
                kwargs[kwarg_key] = value
                structured_fields.add(name)
'''
assert old in s
s=s.replace(old,new)
open(path,'w').write(s)
print("patched")
EOF
cd /app && python /tmp/test_spec.py 2>&1 | tail -3 && python /tmp/edge.py 2>&1 | tail -2 && python -m pytest tests/test_partial.py -q -o addopts="" 2>&1 | tail -3