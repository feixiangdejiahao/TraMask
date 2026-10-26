cd /app && python3 - <<'PY'
p='packages/core/test/prompts/autocomplete.test.ts'
s=open(p).read()
marker = """\ttest('retryBackoff exponential doubles delay each attempt', async () => {"""
insert = """\ttest('a successful retry clears loadError and resets retryCount', async () => {
\t\tlet attempts = 0;
\t\tconst resolver = vi.fn(async () => {
\t\t\tattempts++;
\t\t\tif (attempts <= 2) {
\t\t\t\tthrow new Error('boom');
\t\t\t}
\t\t\treturn [{ value: 'ok' }];
\t\t});
\t\tconst instance = new AutocompletePrompt({
\t\t\tinput,
\t\t\toutput,
\t\t\trender: () => 'foo',
\t\t\toptions: resolver,
\t\t\tmaxRetries: 2,
\t\t\tretryDelay: 100,
\t\t\tdebounceMs: 10,
\t\t});
\t\tinstance.prompt();
\t\tawait vi.advanceTimersByTimeAsync(0); // initial fail -> retry 1
\t\texpect(instance.loading).toBe(true);
\t\tawait vi.advanceTimersByTimeAsync(100); // retry 1 fail -> retry 2
\t\texpect(instance.loading).toBe(true);
\t\tawait vi.advanceTimersByTimeAsync(100); // retry 2 succeeds
\t\texpect(instance.loading).toBe(false);
\t\texpect(instance.loadError).toBe('');
\t\texpect(instance.retryCount).toBe(0);
\t\texpect(instance.filteredOptions).toEqual([{ value: 'ok' }]);
\t});

"""
assert marker in s
s=s.replace(marker, insert + marker)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/autocomplete.test.ts 2>&1 | tail -8