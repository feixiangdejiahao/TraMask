cd /app && python3 - <<'PY'
p='packages/prompts/test/autocomplete.test.ts'
s=open(p).read()
marker = """\ttest('autocompleteMultiselect passes through async options and shows messages', async () => {"""
insert = """\ttest('async autocomplete submits the selected option', async () => {
\t\tconst resolver = vi.fn(async () => [
\t\t\t{ value: 'apple', label: 'Apple' },
\t\t\t{ value: 'banana', label: 'Banana' },
\t\t]);
\t\tconst result = autocomplete({
\t\t\tmessage: 'Pick a fruit',
\t\t\toptions: resolver,
\t\t\tdebounceMs: 10,
\t\t\tinput,
\t\t\toutput,
\t\t});

\t\tawait vi.advanceTimersByTimeAsync(0);
\t\tinput.emit('keypress', '', { name: 'return' });
\t\tconst value = await result;
\t\texpect(value).toBe('apple');
\t});

"""
assert marker in s
s=s.replace(marker, insert + marker)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/prompts && npx vitest run test/autocomplete.test.ts 2>&1 | tail -10