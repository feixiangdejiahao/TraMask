cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()

start = s.index("test('loadError is cleared when typing a new search after exhaustion', async () => {")
end = s.index("describe('AutocompletePrompt async cleanup on new input', () => {")
block = s[start:end]  # includes trailing blank line before describe? ends right before describe
# remove standalone block
s = s[:start] + s[end:]

# insert inside cleanup describe after afterEach
needle = """\tafterEach(() => {
\t\tvi.useRealTimers();
\t\tvi.restoreAllMocks();
\t});

\ttest('typing a new search clears pending retry timer', async () => {"""
# normalize block: strip describe prefix (we removed up to describe). block should end with "});\n\n"
new_test = """\tafterEach(() => {
\t\tvi.useRealTimers();
\t\tvi.restoreAllMocks();
\t});

\ttest('loadError is cleared when typing a new search after exhaustion', async () => {
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

\ttest('typing a new search clears pending retry timer', async () => {"""
assert needle in s, "needle not found"
s=s.replace(needle, new_test)
open(p,'w').write(s)
print("moved")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -8