cd /app && python - <<'EOF'
path = 'src/cattrs/partial.py'
src = open(path).read()

# Make _field_key robust for typeddict alias None
old = '''def _field_key(converter: BaseConverter, a: Any) -> str:
    """The input mapping key for a field."""
    if getattr(converter, "use_alias", False):
        return a.alias
    return a.name
'''
new = '''def _field_key(converter: BaseConverter, a: Any) -> str:
    """The input mapping key for a field."""
    if getattr(converter, "use_alias", False) and a.alias is not None:
        return a.alias
    return a.name
'''
assert old in src
src = src.replace(old, new)

# In _partial_structure_fields, use kwarg_key
old = '''    for a in attrs:
        if not is_typeddict and not a.init:
            # Exclude init=False fields entirely.
            continue

        name = a.name
        key = _field_key(converter, a)

        if key not in obj:
'''
new = '''    for a in attrs:
        if not is_typeddict and not a.init:
            # Exclude init=False fields entirely.
            continue

        name = a.name
        key = _field_key(converter, a)
        kwarg_key = name if is_typeddict else a.alias

        if key not in obj:
'''
assert old in src
src = src.replace(old, new)

# Replace kwargs[a.alias] with kwargs[kwarg_key] in the main loop
src = src.replace("kwargs[a.alias] = sub.value", "kwargs[kwarg_key] = sub.value")
src = src.replace("kwargs[a.alias] = value", "kwargs[kwarg_key] = value")

# Defaults loop: use kwarg_key
old = '''    for a in attrs:
        if (not is_typeddict and not a.init) or a.name in kwargs or a.name not in failed_fields:
            continue
        if _has_default(a):
            kwargs[a.alias] = _get_default(a)
'''
new = '''    for a in attrs:
        if (not is_typeddict and not a.init) or a.name in kwargs or a.name not in failed_fields:
            continue
        if _has_default(a):
            kwarg_key = a.name if is_typeddict else a.alias
            kwargs[kwarg_key] = _get_default(a)
'''
assert old in src
src = src.replace(old, new)

open(path, 'w').write(src)
print("patched")
EOF
cd /app && python /tmp/edge.py