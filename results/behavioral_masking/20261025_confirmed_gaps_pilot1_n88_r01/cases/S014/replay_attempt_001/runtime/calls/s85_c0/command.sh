cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()

# Add retryCount assertion in exhausted test
old = '''\t\texpect(instance.loading).toBe(false);
\t\texpect(instance.loadError).toBe('boom');
\t\texpect(instance.filteredOptions).toEqual(fallback);'''
new = '''\t\texpect(instance.loading).toBe(false);
\t\texpect(instance.loadError).toBe('boom');
\t\texpect(instance.retryCount).toBe(1);
\t\texpect(instance.filteredOptions).toEqual(fallback);'''
assert old in s
s=s.replace(old,new)

# Add test for clearing loadError on new input
old = "\tdescribe('AutocompletePrompt async cleanup on new input', () => {"
new = '''\ttest('loadError is cleared when typing a new search after exhaustion', async () => {
\t\tvi.useFakeTimers();
\t\tlet calls = 0;
\t\tconst resolver = async (search: string) => {
\t\t\tcalls++;
\t\t\tif (calls <= 1) {
\t\t\t\tthrow new Error('boom');
\t\t\t}
\t\t\treturn search ? [{ value: search, label: search }] : fruits;
\t\t};
\t\tconst instance = new AutocompletePrompt({
\t\t\tinput,
\t\t\toutput,
\t\t\trender: () => 'foo',
\t\t\toptions: resolver,
\t\t\tdebounceMs: 10,
\t\t});
\t\tinstance.prompt();
\t\tawait Promise.resolve();
\t\texpect(instance.loadError).toBe('boom');
\t\t// type 'a' -> new fetch, loadError should clear
\t\tinput.emit('keypress', 'a', { name: 'a' });
\t\texpect(instance.loadError).toBeUndefined();
\t\tawait vi.advanceTimersByTimeAsync(20);
\t\texpect(instance.loadError).toBeUndefined();
\t\texpect(instance.filteredOptions).toEqual([{ value: 'a', label: 'a' }]);
\t});

\tdescribe('AutocompletePrompt async cleanup on new input', () => {'''
assert old in s
s=s.replace(old,new,1)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -8