cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()
old = "describe('AutocompletePrompt async cleanup on new input', () => {"
new = '''test('loading is false during debounce when no fetch is in flight', async () => {
	vi.useFakeTimers();
	const resolver = async (search: string) => {
		return search ? [] : fruits;
	};
	const instance = new AutocompletePrompt({
		input,
		output,
		render: () => 'foo',
		options: resolver,
		debounceMs: 100,
	});
	instance.prompt();
	await Promise.resolve();
	expect(instance.loading).toBe(false);
	input.emit('keypress', 'a', { name: 'a' });
	expect(instance.loading).toBe(false);
	await vi.advanceTimersByTimeAsync(50);
	expect(instance.loading).toBe(false);
	await vi.advanceTimersByTimeAsync(50);
	expect(instance.loading).toBe(true);
});

describe('AutocompletePrompt async cleanup on new input', () => {'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -6