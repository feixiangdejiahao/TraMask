cd /app && python3 - <<'PY'
p='packages/core/test/prompts/autocomplete.test.ts'
s=open(p).read()
old = """\t\tresolveB([{ value: 'b-stale' }]);
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\texpect(instance.filteredOptions).toEqual([]);"""
new = """\t\tresolveB([{ value: 'b-stale' }]);
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\t// The stale 'b' result must not be applied.
\t\texpect(instance.filteredOptions).not.toEqual([{ value: 'b-stale' }]);"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/autocomplete.test.ts 2>&1 | tail -8