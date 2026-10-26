cd /app && cat >> packages/core/test/prompts/async-autocomplete.test.ts <<'EOF'

describe('AutocompletePrompt sync function backward compatibility', () => {
	let input: MockReadable;
	let output: MockWritable;

	beforeEach(() => {
		input = new MockReadable();
		output = new MockWritable();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	test('sync function is filtered on user input', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: () => fruits,
		});
		expect(instance.filteredOptions).toEqual(fruits);
		instance.prompt();
		input.emit('keypress', 'a', { name: 'a' });
		expect(instance.filteredOptions).toEqual([
			{ value: 'apple', label: 'Apple' },
			{ value: 'banana', label: 'Banana' },
		]);
		expect(instance.loading).toBe(false);
	});
});
EOF
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -6