cd /app && python - <<'EOF'
path='src/cattrs/partial.py'
s=open(path).read()

old='''        if self._converter is None or self._type is None or self._data is None:
            raise ValueError("This PartialResult cannot be refined.")

        merged = _merge_for_refine(self._converter, self._type, self._data, data, self)
        return self._converter.partial_structure(merged, self._type)
'''
new='''        if self._converter is None or self._type is None or self._data is None:
            raise ValueError("This PartialResult cannot be refined.")

        return self._converter.partial_structure({**self._data, **data}, self._type)
'''
assert old in s
s=s.replace(old,new)

# Remove _merge_for_refine
start = s.find("def _merge_for_refine(")
if start != -1:
    s = s[:start].rstrip() + "\n"

open(path,'w').write(s)
print("switched to simple merge")
EOF
cd /app && python - <<'EOF'
# Update tests to simple merge semantics
path='tests/test_partial.py'
s=open(path).read()
old='''def test_refine_preserves_structured_fields(converter):
    @define
    class A:
        x: int
        y: str = "default"

    res = converter.partial_structure({"x": 1}, A)
    res2 = res.refine({"x": 100, "y": "hello"})
    assert res2.value == A(1, "hello")
'''
new='''def test_refine_new_data_takes_precedence(converter):
    @define
    class A:
        x: int
        y: str = "default"

    res = converter.partial_structure({"x": 1}, A)
    res2 = res.refine({"x": 100, "y": "hello"})
    assert res2.value == A(100, "hello")
'''
assert old in s
s=s.replace(old,new)

old='''def test_refine_nested(converter):
    res = converter.partial_structure({"inner": {"x": 1}, "z": 5}, OuterPartial)
    assert res.value == OuterPartial(InnerPartial(1), 5)
    assert res.failed_fields == frozenset({"inner"})

    res2 = res.refine({"inner": {"y": "world"}})
    assert res2.value == OuterPartial(InnerPartial(1, "world"), 5)
    assert res2.is_complete is True
'''
new='''def test_refine_nested(converter):
    res = converter.partial_structure({"inner": {"x": 1}, "z": 5}, OuterPartial)
    assert res.value == OuterPartial(InnerPartial(1), 5)
    assert res.failed_fields == frozenset({"inner"})

    # New data replaces the nested mapping entirely.
    res2 = res.refine({"inner": {"x": 1, "y": "world"}})
    assert res2.value == OuterPartial(InnerPartial(1, "world"), 5)
    assert res2.is_complete is True
'''
assert old in s
s=s.replace(old,new)
open(path,'w').write(s)
print("tests updated")
EOF
cd /app && python -m pytest tests/test_partial.py -q -o addopts="" 2>&1 | tail -5