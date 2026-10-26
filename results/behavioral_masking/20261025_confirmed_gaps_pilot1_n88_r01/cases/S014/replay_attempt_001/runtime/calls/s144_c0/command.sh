cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
needle = """\ttest('typing a new search clears pending retry timer', async () => {"""
new_test = """\ttest('synchronous throw keeps loading during loadingMinDuration', async () => {
\t\tvi.useFakeTimers();
\t\tconst instance = new AutocompletePrompt({
\t\t\tinput,
\t\t\toutput,
\t\t\trender: () => 'foo',
\t\t\toptions: () => {
\t\t\t\tthrow new Error('boom');
\t\t\t},
\t\t\tloadingMinDuration: 100,
\t\t});
\t\tinstance.prompt();
\t\texpect(instance.loading).toBe(true);
\t\tawait vi.advanceTimersByTimeAsync(99);
\t\texpect(instance.loading).toBe(true);
\t\texpect(instance.loadError).toBeUndefined();
\t\tawait vi.advanceTimersByTimeAsync(1);
\t\texpect(instance.loading).toBe(false);
\t\texpect(instance.loadError).toBe('boom');
\t});

\ttest('typing a new search clears pending retry timer', async () => {"""
assert needle in s
s=s.replace(needle, new_test)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -6