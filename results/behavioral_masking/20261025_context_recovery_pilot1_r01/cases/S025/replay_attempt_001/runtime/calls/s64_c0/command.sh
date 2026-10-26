cd /app && python3 - <<'PY'
p='packages/core/test/prompts/autocomplete.test.ts'
s=open(p).read()

# Fix clearCache test
old = """\t\tinstance.clearCache();
\t\tinstance.emit('userInput', 'a');
\t\tawait vi.advanceTimersByTimeAsync(10);
\t\texpect(resolver).toHaveBeenCalledTimes(3);"""
new = """\t\t// Change input away from 'a' so emitting 'a' again is a real search change.
\t\tinstance.emit('userInput', 'b');
\t\tawait vi.advanceTimersByTimeAsync(10);
\t\texpect(resolver).toHaveBeenCalledTimes(3);

\t\tinstance.clearCache();
\t\tinstance.emit('userInput', 'a');
\t\tawait vi.advanceTimersByTimeAsync(10);
\t\texpect(resolver).toHaveBeenCalledTimes(4);"""
assert old in s
s=s.replace(old,new)

# Fix staleWhileRevalidate test: type 'b' before returning to 'a'
old = """\t\tresolver.mockImplementation(async (search: string) => [{ value: `${search}-v2` }]);
\t\tinstance.emit('userInput', 'a');
\t\t// Cache hit serves immediately
\t\texpect(instance.filteredOptions).toEqual([{ value: 'a-v1' }]);
\t\texpect(instance.loading).toBe(true);"""
new = """\t\tresolver.mockImplementation(async (search: string) => [{ value: `${search}-v2` }]);
\t\tinstance.emit('userInput', 'b');
\t\tawait vi.advanceTimersByTimeAsync(10);
\t\tinstance.emit('userInput', 'a');
\t\t// Cache hit serves immediately
\t\texpect(instance.filteredOptions).toEqual([{ value: 'a-v1' }]);
\t\texpect(instance.loading).toBe(true);"""
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/autocomplete.test.ts 2>&1 | tail -15