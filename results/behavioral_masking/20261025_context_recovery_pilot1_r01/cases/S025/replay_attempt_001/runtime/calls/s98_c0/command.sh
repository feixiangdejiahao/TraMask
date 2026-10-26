cd /app && python3 - <<'PY'
p='packages/core/test/prompts/autocomplete.test.ts'
s=open(p).read()
marker = """\ttest('entering searchTooShort cancels a pending debounced fetch', async () => {"""
insert = """\ttest('an in-flight fetch is invalidated as soon as input changes, even during debounce', async () => {
\t\tlet resolveB: (value: { value: string }[]) => void = () => {};
\t\tconst resolver = vi.fn((search: string) => {
\t\t\tif (search === 'b') {
\t\t\t\treturn new Promise<{ value: string }[]>((resolve) => {
\t\t\t\t\tresolveB = resolve;
\t\t\t\t});
\t\t\t}
\t\t\treturn Promise.resolve([{ value: `${search}-new` }]);
\t\t});
\t\tconst instance = new AutocompletePrompt({
\t\t\tinput,
\t\t\toutput,
\t\t\trender: () => 'foo',
\t\t\toptions: resolver,
\t\t\tdebounceMs: 10,
\t\t});
\t\tinstance.prompt();
\t\tawait vi.advanceTimersByTimeAsync(0); // initial ''

\t\tinstance.emit('userInput', 'b');
\t\tawait vi.advanceTimersByTimeAsync(10); // start slow fetch for 'b'

\t\tinstance.emit('userInput', 'ba'); // invalidates 'b' immediately, schedules 'ba'
\t\t// The stale 'b' fetch resolves before the 'ba' debounce fires.
\t\tresolveB([{ value: 'b-stale' }]);
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\texpect(instance.filteredOptions).toEqual([]);

\t\tawait vi.advanceTimersByTimeAsync(10); // debounce fires, fetch 'ba'
\t\tawait vi.advanceTimersByTimeAsync(0);
\t\texpect(instance.filteredOptions).toEqual([{ value: 'ba-new' }]);
\t});

"""
assert marker in s
s=s.replace(marker, insert + marker)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && pnpm build 2>&1 | tail -2 && npx vitest run test/prompts/autocomplete.test.ts 2>&1 | tail -12