cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()

start = s.index("test('loading is false during debounce when no fetch is in flight', async () => {")
end = s.index("describe('AutocompletePrompt async cleanup on new input', () => {")
block = s[start:end]
s = s[:start] + s[end:]

needle = """\tafterEach(() => {
\t\tvi.useRealTimers();
\t\tvi.restoreAllMocks();
\t});

\ttest('loadError is cleared when typing a new search after exhaustion', async () => {"""
new_test = """\tafterEach(() => {
\t\tvi.useRealTimers();
\t\tvi.restoreAllMocks();
\t});

\ttest('loading is false during debounce when no fetch is in flight', async () => {
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

\ttest('loadError is cleared when typing a new search after exhaustion', async () => {"""
assert needle in s
s=s.replace(needle, new_test)
open(p,'w').write(s)
print("moved")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -6