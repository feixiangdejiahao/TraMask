cd /app && python - <<'PY'
path = 'bandit/formatters/text.py'
src = open(path).read()

old = '''    bits.append(f"Files excluded ({len(manager.excluded_files)}):")
    bits.extend([f"\\t{fname}" for fname in manager.excluded_files])
    return "\\n".join([bit for bit in bits])
'''
new = '''    bits.append(f"Files excluded ({len(manager.excluded_files)}):")
    bits.extend([f"\\t{fname}" for fname in manager.excluded_files])

    if hasattr(manager, "files_cached"):
        bits.append(
            f"Files cached: {len(manager.files_cached)}, "
            f"Files scanned: {len(manager.files_scanned)}"
        )
        if getattr(manager, "invalidation_reasons", None):
            bits.append("Invalidation reasons:")
            for reason, count in sorted(manager.invalidation_reasons.items()):
                bits.append(f"\\t{reason}: {count}")

    return "\\n".join([bit for bit in bits])
'''
assert old in src
src = src.replace(old, new, 1)
open(path, 'w').write(src)
PY
python -m py_compile bandit/formatters/text.py && echo OK