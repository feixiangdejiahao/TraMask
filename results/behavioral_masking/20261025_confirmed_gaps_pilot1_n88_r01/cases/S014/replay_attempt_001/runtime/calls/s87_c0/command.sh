cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = "describe('AutocompletePrompt async cleanup on new input', () => {"
new = '''test('loadError is cleared when typing a new search after exhaustion', async () => {
	vi.useFakeTimers();
	let calls = 0;
	const resolver = async (search: string) => {
		calls++;
		if (calls <= 1) {
			throw new Error('boom');
		}
		return search ? [{ value: search, label: search }] : fruits;
	};
	const instance = new AutocompletePrompt({
		input,
		output,
		render: () => 'foo',
		options: resolver,
		debounceMs: 10,
	});
	instance.prompt();
	await Promise.resolve();
	expect(instance.loadError).toBe('boom');
	// type 'a' -> new fetch, loadError should clear
	input.emit('keypress', 'a', { name: 'a' });
	expect(instance.loadError).toBeUndefined();
	await vi.advanceTimersByTimeAsync(20);
	expect(instance.loadError).toBeUndefined();
	expect(instance.filteredOptions).toEqual([{ value: 'a', label: 'a' }]);
});

describe('AutocompletePrompt async cleanup on new input', () => {'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -8