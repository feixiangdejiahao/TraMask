cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = "\tdescribe('AutocompletePrompt async cleanup on new input', () => {"
new = '''\ttest('loading is false during debounce when no fetch is in flight', async () => {
\t\tvi.useFakeTimers();
\t\tconst resolver = async (search: string) => {
\t\t\treturn search ? [] : fruits;
\t\t};
\t\tconst instance = new AutocompletePrompt({
\t\t\tinput,
\t\t\toutput,
\t\t\trender: () => 'foo',
\t\t\toptions: resolver,
\t\t\tdebounceMs: 100,
\t\t});
\t\tinstance.prompt();
\t\tawait Promise.resolve();
\t\texpect(instance.loading).toBe(false);
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\texpect(instance.loading).toBe(false);
\t\tawait vi.advanceTimersByTimeAsync(50);
\t\texpect(instance.loading).toBe(false);
\t\tawait vi.advanceTimersByTimeAsync(50);
\t\texpect(instance.loading).toBe(true);
\t});

\tdescribe('AutocompletePrompt async cleanup on new input', () => {'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -6