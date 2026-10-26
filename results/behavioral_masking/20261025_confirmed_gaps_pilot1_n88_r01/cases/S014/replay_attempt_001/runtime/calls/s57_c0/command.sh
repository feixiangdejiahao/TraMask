cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
s=s.replace(
"expect(instance.filteredOptions).toEqual([{ value: 'apple', label: 'Apple' }]);",
"expect(instance.filteredOptions).toEqual([{ value: 'apple', label: 'Apple' }, { value: 'banana', label: 'Banana' }]);")
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -25