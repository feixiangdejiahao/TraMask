cd /app && python - <<'EOF'
path = 'src/cattrs/partial.py'
src = open(path).read()

old = '''        if key not in obj:
            failed_fields.add(name)
            if required(a):
                missing_required = True
            continue
'''
new = '''        if key not in obj:
            failed_fields.add(name)
            exc = AttributeError(f"Missing field {name}")
            error_map[name] = exc
            errors.append(exc)
            if required(a):
                missing_required = True
            continue
'''
assert old in src
src = src.replace(old, new)

old2 = '''                elif sub.value is not None:
                    # Use the partial value but mark the field as failed.
                    kwargs[a.alias] = sub.value
                    failed_fields.add(name)
                    if sub.errors is not None:
                        exc = sub.errors
                        _add_note(detailed_validation, exc, cl, name, t)
                        error_map[name] = exc
                        errors.append(exc)
                    else:
                        exc = ClassValidationError(
                            f"While structuring {_unwrap_type(t)!r}", [], _unwrap_type(t)
                        )
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
                    else:
                        exc = ClassValidationError(
                            f"While structuring {_unwrap_type(t)!r}", [], _unwrap_type(t)
                        )
                        _add_note(detailed_validation, exc, cl, name, t)
                        error_map[name] = exc
                        errors.append(exc)
                    if required(a):
                        missing_required = True
'''
new2 = '''                elif sub.value is not None:
                    # Use the partial value but mark the field as failed.
                    kwargs[a.alias] = sub.value
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
assert old2 in src
src = src.replace(old2, new2)

open(path, 'w').write(src)
print("patched")
EOF
cd /app && python /tmp/repro.py