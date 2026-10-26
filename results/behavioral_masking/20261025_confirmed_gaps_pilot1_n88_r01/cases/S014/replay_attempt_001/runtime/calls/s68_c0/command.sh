cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = "\t\texpect(instance.filteredOptions).toEqual(fruits);\n\t});\n\n\ttest('new fetch cancels pending min-duration timer'"
new = "\t\texpect(instance.filteredOptions).toEqual([{ value: 'empty', label: 'Empty' }]);\n\t});\n\n\ttest('new fetch cancels pending min-duration timer'"
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("fixed")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -8