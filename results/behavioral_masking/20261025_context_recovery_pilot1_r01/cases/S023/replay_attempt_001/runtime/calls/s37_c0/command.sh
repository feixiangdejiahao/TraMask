cd /app && python - <<'EOF'
path = 'src/cattrs/partial.py'
src = open(path).read()

# update typeddict to pass is_typeddict flag
old = '''    return _partial_structure_fields(
        converter, obj, origin, attrs, required=lambda a: a.name in req_keys
    )
'''
new = '''    return _partial_structure_fields(
        converter,
        obj,
        origin,
        attrs,
        required=lambda a: a.name in req_keys,
        is_typeddict=True,
    )
'''
assert old in src
src = src.replace(old, new)

# update signature
old = '''def _partial_structure_fields(
    converter: BaseConverter,
    obj: Mapping[str, Any],
    cl: type,
    attrs: list[Any],
    *,
    required: Any,
) -> PartialResult:
'''
new = '''def _partial_structure_fields(
    converter: BaseConverter,
    obj: Mapping[str, Any],
    cl: type,
    attrs: list[Any],
    *,
    required: Any,
    is_typeddict: bool = False,
) -> PartialResult:
'''
assert old in src
src = src.replace(old, new)

# update init skip
old = '''    for a in attrs:
        if not a.init:
            # Exclude init=False fields entirely.
            continue
'''
new = '''    for a in attrs:
        if not is_typeddict and not a.init:
            # Exclude init=False fields entirely.
            continue
'''
assert old in src
src = src.replace(old, new)

# update defaults loop skip condition
old = '''    for a in attrs:
        if not a.init or a.name in kwargs or a.name not in failed_fields:
            continue
'''
new = '''    for a in attrs:
        if (not is_typeddict and not a.init) or a.name in kwargs or a.name not in failed_fields:
            continue
'''
assert old in src
src = src.replace(old, new)

# update allowed_keys
old = '''    allowed_keys = {_field_key(converter, a) for a in attrs if a.init}
'''
new = '''    if is_typeddict:
        allowed_keys = {_field_key(converter, a) for a in attrs}
    else:
        allowed_keys = {_field_key(converter, a) for a in attrs if a.init}
'''
assert old in src
src = src.replace(old, new)

# update value construction condition
old = '''        if is_typeddict(get_origin(cl) or cl):
            # TypedDicts are dicts; only include structured/failed-with-value keys.
            value = kwargs
'''
new = '''        if is_typeddict:
            # TypedDicts are dicts; only include structured/failed-with-value keys.
            value = kwargs
'''
assert old in src
src = src.replace(old, new)

open(path, 'w').write(src)
print("patched")
EOF
cd /app && python /tmp/test_spec.py