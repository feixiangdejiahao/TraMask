cd /app && python - <<'EOF'
path='tests/test_partial.py'
s=open(path).read()
old='''    res = converter.partial_structure({"a": "not an int"}, A)
    # `a` is required and failed, so no value can be produced.
    assert res.value is None
    assert res.structured_fields == frozenset({"b"})
    assert res.failed_fields == frozenset({"a"})'''
new='''    res = converter.partial_structure({"a": "not an int"}, A)
    # `a` is required and failed, so no value can be produced.
    assert res.value is None
    assert res.structured_fields == frozenset()
    assert res.failed_fields == frozenset({"a", "b"})'''
assert old in s
s=s.replace(old,new)

old='''    res = converter.partial_structure({"x": "bad"}, A)
    assert res.value == A(1)
    assert res.failed_fields == frozenset({"x"})
    assert res.errors is not None
    assert "x" in res.error_map'''
new='''    res = converter.partial_structure({"x": 1, "y": "bad"}, A)
    assert res.value == A(1)
    assert res.failed_fields == frozenset({"y"})
    assert res.errors is not None
    assert "y" in res.error_map'''
assert old in s
s=s.replace(old,new)
open(path,'w').write(s)
EOF
cd /app && timeout 30 python -m pytest tests/test_partial.py -q -o addopts="" 2>&1 | tail -15