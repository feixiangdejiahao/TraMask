cd /app && cat >> packages/core/test/prompts/async-autocomplete.test.ts <<'EOF'

describe('AutocompletePrompt async initial values', () => {
	let input: MockReadable;
	let output: MockWritable;

	beforeEach(() => {
		input = new MockReadable();
		output = new MockWritable();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	test('initialValue selects the matching async option', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: async () => fruits,
			initialValue: ['cherry'],
		});
		await Promise.resolve();
		await Promise.resolve();
		expect(instance.cursor).toBe(2);
		expect(instance.selectedValues).toEqual(['cherry']);
		expect(instance.focusedValue).toBe('cherry');
	});

	test('non-multiple defaults to first async option', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: async () => fruits,
		});
		await Promise.resolve();
		await Promise.resolve();
		expect(instance.cursor).toBe(0);
		expect(instance.selectedValues).toEqual(['apple']);
	});

	test('multiple stays empty until selection', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: async () => fruits,
			multiple: true,
		});
		await Promise.resolve();
		await Promise.resolve();
		expect(instance.cursor).toBe(0);
		expect(instance.selectedValues).toEqual([]);
	});
});
EOF
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -8