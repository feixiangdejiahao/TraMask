cd /app && python - <<'EOF'
path='HISTORY.md'
s=open(path).read()
old='''## NEXT (UNRELEASED)

- Add the {mod}`tomllib <cattrs.preconf.tomllib>` preconf converter.
'''
new='''## NEXT (UNRELEASED)

- Add {meth}`BaseConverter.partial_structure <cattrs.BaseConverter.partial_structure>` and the top-level {func}`cattrs.partial_structure`, which can be used to partially structure attrs classes, dataclasses and TypedDicts from incomplete input mappings.
  The results are represented by {class}`cattrs.PartialResult`.
  See [here](https://catt.rs/en/latest/partial.html) for more details.
  ([#718](https://github.com/python-attrs/cattrs/pull/718))
- Add the {mod}`tomllib <cattrs.preconf.tomllib>` preconf converter.
'''
assert old in s
open(path,'w').write(s.replace(old,new))
print("history updated")
EOF
cd /app && git diff --stat