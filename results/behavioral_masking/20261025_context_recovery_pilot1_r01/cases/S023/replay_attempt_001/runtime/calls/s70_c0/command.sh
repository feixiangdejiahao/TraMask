cd /app && python - <<'EOF'
path = 'src/cattrs/partial.py'
src = open(path).read()

# Absent branch: no error/error_map entry
old = '''        if key not in obj:
            failed_fields.add(name)
            exc = AttributeError(f"Missing field {name}")
            _add_note(detailed_validation, exc, cl, name, a.type)
            error_map[name] = exc
            errors.append(exc)
            if required(a):
                missing_required = True
            continue
'''
new = '''        if key not in obj:
            failed_fields.add(name)
            if required(a):
                missing_required = True
            continue
'''
assert old in src
src = src.replace(old, new)

# Nested partial with value: only add error if sub.errors is not None
old = '''                elif sub.value is not None:
                    # Use the partial value but mark the field as failed.
                    kwargs[kwarg_key] = sub.value
                    failed_fields.add(name)
                    if sub.errors is not None:
                        exc = sub.errors
                    else:
                        exc = ValueError(f"Field {name} is incomplete")
                    _add_note(detailed_validation, exc, cl, name, t)
                    error_map[name] = exc
                    errors.append(exc)
                else:
                    # No value can be produced at all; normal field failure.
                    failed_fields.add(name)
                    if sub.errors is not None:
                        exc = sub.errors
                    else:
                        exc = ValueError(f"Field {name} could not be structured")
                    _add_note(detailed_validation, exc, cl, name, t)
                    error_map[name] = exc
                    errors.append(exc)
                    if required(a):
                        missing_required = True
'''
new = '''                elif sub.value is not None:
                    # Use the partial value but mark the field as failed.
                    kwargs[kwarg_key] = sub.value
                    failed_fields.add(name)
                    if sub.errors is not None:
                        exc = sub.errors
                        _add_note(detailed_validation, exc, cl, name, t)
                        error_map[name] = exc
                        errors.append(exc)
                else:
                    # No value can be produced at all; normal field failure.
                    failed_fields.add(name)
                    if sub.errors is not None:
                        exc = sub.errors
                        _add_note(detailed_validation, exc, cl, name, t)
                        error_map[name] = exc
                        errors.append(exc)
                    if required(a):
                        missing_required = True
'''
assert old in src
src = src.replace(old, new)

open(path, 'w').write(src)
print("patched")
EOF
cd /app && python /tmp/test_spec.py 2>&1 | tail -20