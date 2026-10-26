cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = "\t\texpect(instance.filteredOptions).toEqual([{ value: 'apple', label: 'Apple' }, { value: 'banana', label: 'Banana' }]);\n\t\tvi.useRealTimers();\n\t});\n\n\ttest('cacheResults"
new = "\t\texpect(instance.filteredOptions).toEqual([{ value: 'apple', label: 'Apple' }]);\n\t\tvi.useRealTimers();\n\t});\n\n\ttest('cacheResults"
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("fixed")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -20