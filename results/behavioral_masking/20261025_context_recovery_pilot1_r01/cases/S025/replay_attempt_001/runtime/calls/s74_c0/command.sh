cd /app && python3 - <<'PY'
p='packages/core/test/prompts/autocomplete.test.ts'
s=open(p).read()
marker = """\ttest('AbortError is silently ignored', async () => {"""
insert = """\ttest('entering searchTooShort cancels a pending debounced fetch', async () => {
\t\tconst resolver = vi.fn(async () => [{ value: 'x' }]);
\t\tconst instance = new AutocompletePrompt({
\t\t\tinput,
\t\t\toutput,
\t\t\trender: () => 'foo',
\t\t\toptions: resolver,
\t\t\tminSearchLength: 2,
\t\t\tdebounceMs: 10,
\t\t});
\t\tinstance.prompt();
\t\tawait vi.advanceTimersByTimeAsync(0); // initial ''

\t\tinstance.emit('userInput', 'ab'); // schedules debounce for 'ab'
\t\tinstance.emit('userInput', 'a'); // too short; must cancel debounce
\t\tawait vi.advanceTimersByTimeAsync(50);
\t\texpect(resolver).toHaveBeenCalledTimes(1); // never fetched 'ab'
\t\texpect(instance.searchTooShort).toBe(true);
\t});

"""
assert marker in s
s=s.replace(marker, insert + marker)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && pnpm build 2>&1 | tail -2 && npx vitest run test/prompts/autocomplete.test.ts 2>&1 | tail -8