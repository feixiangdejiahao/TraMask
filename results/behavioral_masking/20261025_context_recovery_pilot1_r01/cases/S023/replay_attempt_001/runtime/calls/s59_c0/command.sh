cd /app && python - <<'EOF'
path = 'src/cattrs/partial.py'
src = open(path).read()

old = '''        if key not in obj:
            failed_fields.add(name)
            exc = AttributeError(f"Missing field {name}")
            error_map[name] = exc
            errors.append(exc)
            if required(a):
                missing_required = True
            continue
'''
new = '''        if key not in obj:
            failed_fields.add(name)
            exc = AttributeError(f"Missing field {name}")
            _add_note(detailed_validation, exc, cl, name, a.type)
            error_map[name] = exc
            errors.append(exc)
            if required(a):
                missing_required = True
            continue
'''
assert old in src
src = src.replace(old, new)
open(path, 'w').write(src)
print("patched")
EOF
cd /app && python /tmp/errcheck.py