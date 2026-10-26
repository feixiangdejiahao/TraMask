cd /app && cat >> packages/core/test/prompts/async-autocomplete.test.ts <<'EOF'

describe('AutocompletePrompt async cleanup on new input', () => {
	let input: MockReadable;
	let output: MockWritable;

	beforeEach(() => {
		input = new MockReadable();
		output = new MockWritable();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	test('typing a new search clears pending retry timer', async () => {
		vi.useFakeTimers();
		const searches: string[] = [];
		const resolver = async (search: string) => {
			searches.push(search);
			throw new Error('boom');
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			maxRetries: 1,
			retryDelay: 100,
			debounceMs: 10,
		});
		instance.prompt();
		await Promise.resolve();
		expect(searches).toEqual(['']);
		expect(instance.loading).toBe(true);
		// retry for '' is pending; type 'a' -> debounced fetch for 'a'
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(10);
		expect(searches).toEqual(['', 'a']);
		// old retry timer must not fire for ''
		await vi.advanceTimersByTimeAsync(500);
		expect(searches).toEqual(['', 'a']);
	});
});
EOF
cd /app && pnpm --filter @clack/core run build >/dev/null 2>&1 && cd packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -12