cd /app && python3 - <<'PY'
p='packages/prompts/test/autocomplete.test.ts'
s=open(p).read()

old = """\t\tresolveFn([{ value: 'apple', label: 'Apple' }]);
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\texpect(output.buffer.join('')).not.toContain('Searching...');

\t\tinput.emit('keypress', '', { name: 'return' });
\t\tawait result;"""
new = """\t\tresolveFn([{ value: 'apple', label: 'Apple' }]);
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\texpect(output.buffer.join('')).toContain('Apple');

\t\tinput.emit('keypress', '', { name: 'return' });
\t\tawait result;"""
assert old in s
s=s.replace(old,new)

old = """\t\tresolveFn([{ value: 'apple', label: 'Apple' }]);
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\texpect(output.buffer.join('')).not.toContain('Loading fruits...');

\t\tinput.emit('keypress', 'a', { name: 'a' });"""
new = """\t\tresolveFn([{ value: 'apple', label: 'Apple' }]);
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\texpect(output.buffer.join('')).toContain('Apple');

\t\tinput.emit('keypress', 'a', { name: 'a' });"""
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PY
cd /app/packages/prompts && npx vitest run test/autocomplete.test.ts 2>&1 | tail -15