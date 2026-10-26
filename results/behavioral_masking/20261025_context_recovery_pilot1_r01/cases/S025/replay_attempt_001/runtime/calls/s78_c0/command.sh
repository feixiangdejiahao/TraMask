cd /app && python3 - <<'PY'
p='packages/core/test/prompts/autocomplete.test.ts'
s=open(p).read()
marker = """\ttest('close aborts in-flight fetches and resets transient state', async () => {"""
insert = """\ttest('a new fetch cancels a pending loadingMinDuration timer', async () => {
\t\tlet resolveA: (value: { value: string }[]) => void = () => {};
\t\tconst resolver = vi.fn((search: string) => {
\t\t\tif (search === 'a') {
\t\t\t\treturn new Promise<{ value: string }[]>((resolve) => {
\t\t\t\t\tresolveA = resolve;
\t\t\t\t});
\t\t\t}
\t\t\treturn Promise.resolve([{ value: 'b' }]);
\t\t});
\t\tconst instance = new AutocompletePrompt({
\t\t\tinput,
\t\t\toutput,
\t\t\trender: () => 'foo',
\t\t\toptions: resolver,
\t\t\tloadingMinDuration: 200,
\t\t\tdebounceMs: 10,
\t\t});
\t\tinstance.prompt();
\t\tawait vi.advanceTimersByTimeAsync(0); // initial ''

\t\tinstance.emit('userInput', 'a');
\t\tawait vi.advanceTimersByTimeAsync(10); // fetch a
\t\tresolveA([{ value: 'a' }]);
\t\tawait vi.advanceTimersByTimeAsync(0); // result arrives, min-duration timer pending
\t\texpect(instance.loading).toBe(true);

\t\tinstance.emit('userInput', 'b');
\t\tawait vi.advanceTimersByTimeAsync(10); // new fetch cancels min-duration timer
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\t// 'a' must not be applied later
\t\tawait vi.advanceTimersByTimeAsync(200);
\t\texpect(instance.filteredOptions).toEqual([{ value: 'b' }]);
\t\texpect(instance.loading).toBe(false);
\t});

"""
assert marker in s
s=s.replace(marker, insert + marker)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/autocomplete.test.ts 2>&1 | tail -10