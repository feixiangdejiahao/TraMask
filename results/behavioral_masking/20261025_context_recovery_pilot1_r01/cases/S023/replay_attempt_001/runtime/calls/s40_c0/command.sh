cd /app && python - <<'EOF'
path = 'src/cattrs/partial.py'
src = open(path).read()

old = '''        if self._converter is None or self._type is None or self._data is None:
            raise ValueError("This PartialResult cannot be refined.")

        merged = _merge_for_refine(self._converter, self._type, self._data, data, self)
        return self._converter.partial_structure(merged, self._type)
'''
new = '''        if self._converter is None or self._type is None or self._data is None:
            raise ValueError("This PartialResult cannot be refined.")

        return self._converter.partial_structure({**self._data, **data}, self._type)
'''
assert old in src
src = src.replace(old, new)

# remove _merge_for_refine function
start = src.find("def _merge_for_refine(")
if start != -1:
    src = src[:start].rstrip() + "\n"

open(path, 'w').write(src)
print("patched")
EOF
tail -20 src/cattrs/partial.py