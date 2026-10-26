cd /app && cat >> packages/prompts/test/autocomplete.test.ts <<'EOF'

describe('autocomplete async options', () => {
	let input: MockReadable;
	let output: MockWritable;

	beforeEach(() => {
		input = new MockReadable();
		output = new MockWritable();
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	const flush = async () => {
		await Promise.resolve();
		await Promise.resolve();
	};

	test('shows loadingMessage while fetching', async () => {
		let resolveFn: (value: { value: string; label: string }[]) => void = () => {};
		const resolver = () =>
			new Promise<{ value: string; label: string }[]>((resolve) => {
				resolveFn = resolve;
			});

		const result = autocomplete({
			message: 'Pick a fruit',
			options: resolver,
			loadingMessage: 'Searching...',
			debounceMs: 10,
			input,
			output,
		});

		await vi.advanceTimersByTimeAsync(0);
		expect(output.buffer.join('')).toContain('Searching...');

		resolveFn([{ value: 'apple', label: 'Apple' }]);
		await vi.advanceTimersByTimeAsync(0);
		expect(output.buffer.join('')).not.toContain('Searching...');

		input.emit('keypress', '', { name: 'return' });
		await result;
	});

	test('shows Type at least N characters when search is too short', async () => {
		const resolver = vi.fn(async () => [{ value: 'apple', label: 'Apple' }]);
		const result = autocomplete({
			message: 'Pick a fruit',
			options: resolver,
			minSearchLength: 3,
			debounceMs: 10,
			input,
			output,
		});

		await vi.advanceTimersByTimeAsync(0);
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(0);
		expect(output.buffer.join('')).toContain('Type at least 3 characters');
		expect(resolver).toHaveBeenCalledTimes(1); // only initial empty fetch

		input.emit('keypress', 'b', { name: 'b' });
		input.emit('keypress', 'c', { name: 'c' });
		await vi.advanceTimersByTimeAsync(10);
		await vi.advanceTimersByTimeAsync(0);
		expect(resolver).toHaveBeenCalledTimes(2);

		input.emit('keypress', '', { name: 'return' });
		await result;
	});

	test('honors noResultsMessage override', async () => {
		const resolver = vi.fn(async () => []);
		const result = autocomplete({
			message: 'Pick a fruit',
			options: resolver,
			noResultsMessage: 'Nothing here yet',
			debounceMs: 10,
			input,
			output,
		});

		await vi.advanceTimersByTimeAsync(0);
		input.emit('keypress', 'z', { name: 'z' });
		await vi.advanceTimersByTimeAsync(10);
		await vi.advanceTimersByTimeAsync(0);
		expect(output.buffer.join('')).toContain('Nothing here yet');

		input.emit('keypress', '', { name: 'return' });
		await result;
	});

	test('autocompleteMultiselect passes through async options and shows messages', async () => {
		let resolveFn: (value: { value: string; label: string }[]) => void = () => {};
		const resolver = () =>
			new Promise<{ value: string; label: string }[]>((resolve) => {
				resolveFn = resolve;
			});

		const result = autocompleteMultiselect({
			message: 'Pick fruits',
			options: resolver,
			loadingMessage: 'Loading fruits...',
			minSearchLength: 2,
			debounceMs: 10,
			input,
			output,
		});

		await vi.advanceTimersByTimeAsync(0);
		expect(output.buffer.join('')).toContain('Loading fruits...');

		resolveFn([{ value: 'apple', label: 'Apple' }]);
		await vi.advanceTimersByTimeAsync(0);
		expect(output.buffer.join('')).not.toContain('Loading fruits...');

		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(0);
		expect(output.buffer.join('')).toContain('Type at least 2 characters');

		input.emit('keypress', '', { name: 'return' });
		await result;
	});
});
EOF
cd /app/packages/prompts && npx vitest run test/autocomplete.test.ts 2>&1 | tail -40