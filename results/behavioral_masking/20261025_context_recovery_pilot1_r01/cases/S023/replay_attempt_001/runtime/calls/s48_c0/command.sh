cd /app && python - <<'EOF'
path = 'src/cattrs/partial.py'
src = open(path).read()

old = '''        if self._converter is None or self._type is None or self._data is None:
            raise ValueError("This PartialResult cannot be refined.")

        return self._converter.partial_structure({**self._data, **data}, self._type)
'''
new = '''        if self._converter is None or self._type is None or self._data is None:
            raise ValueError("This PartialResult cannot be refined.")

        merged = _merge_for_refine(self._converter, self._type, self._data, data, self)
        return self._converter.partial_structure(merged, self._type)
'''
assert old in src
src = src.replace(old, new)

# append _merge_for_refine function at end
src += '''

def _merge_for_refine(
    converter: BaseConverter,
    cl: type,
    old_data: Mapping[str, Any],
    new_data: Mapping[str, Any],
    prev: PartialResult,
) -> dict[str, Any]:
    """Merge new data into old data for refinement.

    Fields already structured are preserved. For failed nested fields, the
    new data is merged recursively into the nested data.
    """
    merged = dict(old_data)

    origin = get_origin(cl) or cl
    if has(origin):
        attrs = adapted_fields(origin)
    elif is_typeddict(origin):
        attrs = typeddict_adapted_fields(origin)
    else:
        attrs = []

    fields_by_name = {a.name: a for a in attrs}

    for name, value in new_data.items():
        if name in prev.structured_fields:
            # Preserve already structured fields.
            continue

        a = fields_by_name.get(name)
        if (
            a is not None
            and _is_partial_type(a.type)
            and isinstance(old_data.get(name), Mapping)
            and isinstance(value, Mapping)
        ):
            sub_prev = converter.partial_structure(old_data[name], _unwrap_type(a.type))
            merged[name] = _merge_for_refine(
                converter, _unwrap_type(a.type), old_data[name], value, sub_prev
            )
        else:
            merged[name] = value

    return merged
'''
open(path, 'w').write(src)
print("restored recursive refine")
EOF
cd /app && python - <<'EOF'
# update test nested refine back to recursive behavior
path='/tmp/test_spec.py'
s=open(path).read()
old='''r2 = r.refine({"inner": {"y": "w"}})
print("refine nested:", r2.value, r2.is_complete, r2.structured_fields, r2.failed_fields)
# simple merge: inner replaced entirely, so x missing -> inner has no value
assert r2.value is None'''
new='''r2 = r.refine({"inner": {"y": "w"}})
print("refine nested:", r2.value, r2.is_complete, r2.structured_fields, r2.failed_fields)
assert r2.value == Outer(Inner(1, "w"), 5)
assert r2.is_complete'''
assert old in s
open(path,'w').write(s.replace(old,new))
EOF
cd /app && python /tmp/test_spec.py