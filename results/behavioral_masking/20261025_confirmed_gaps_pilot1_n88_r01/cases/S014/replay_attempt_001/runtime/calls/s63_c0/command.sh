cd /app && cat >> packages/core/test/prompts/async-autocomplete.test.ts <<'EOF'

describe('AutocompletePrompt async edge cases', () => {
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

	test('loadingMinDuration defers error application too', async () => {
		vi.useFakeTimers();
		const resolver = async () => {
			throw new Error('boom');
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			loadingMinDuration: 100,
		});
		instance.prompt();
		await Promise.resolve();
		expect(instance.loading).toBe(true);
		expect(instance.loadError).toBeUndefined();
		await vi.advanceTimersByTimeAsync(99);
		expect(instance.loading).toBe(true);
		expect(instance.loadError).toBeUndefined();
		await vi.advanceTimersByTimeAsync(1);
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBe('boom');
	});

	test('maxCacheSize evicts oldest entries', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const resolver = async (search: string) => {
			calls++;
			return [{ value: search || 'empty', label: search || 'empty' }];
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			cacheResults: true,
			maxCacheSize: 2,
			debounceMs: 10,
		});
		instance.prompt();
		await Promise.resolve();
		expect(calls).toBe(1); // ''
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(2);
		input.emit('keypress', 'b', { name: 'b' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(3);
		// 'b' evicts ''; typing 'a' is still cached
		input.emit('keypress', '\u007f', { name: 'backspace' });
		await vi.advanceTimersByTimeAsync(20);
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(3);
		// 'a' is cached; clearing to '' evicts 'a' (size 2: 'a','b' -> add '' evicts 'a')
		input.emit('keypress', '\u007f', { name: 'backspace' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(4);
	});

	test('exponential backoff doubles delay', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const resolver = async () => {
			calls++;
			if (calls <= 2) {
				throw new Error('boom');
			}
			return fruits;
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			maxRetries: 2,
			retryDelay: 50,
			retryBackoff: 'exponential',
		});
		instance.prompt();
		await Promise.resolve();
		expect(instance.retryCount).toBe(1);
		// first retry after 50ms
		await vi.advanceTimersByTimeAsync(50);
		await Promise.resolve();
		expect(calls).toBe(2);
		expect(instance.retryCount).toBe(2);
		// second retry after 100ms
		await vi.advanceTimersByTimeAsync(99);
		expect(calls).toBe(2);
		await vi.advanceTimersByTimeAsync(1);
		await Promise.resolve();
		expect(calls).toBe(3);
		expect(instance.loading).toBe(false);
	});

	test('entering searchTooShort aborts in-flight fetch', async () => {
		vi.useFakeTimers();
		const signals: AbortSignal[] = [];
		const resolvers = new Map<string, (v: typeof fruits) => void>();
		const resolver = (search: string, opts: { signal: AbortSignal }) => {
			signals.push(opts.signal);
			return new Promise<typeof fruits>((resolve) => {
				resolvers.set(search, resolve);
			});
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			minSearchLength: 2,
			debounceMs: 10,
		});
		instance.prompt();
		expect(signals.length).toBe(1);
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(20);
		expect(signals.length).toBe(2);
		expect(instance.loading).toBe(true);
		// backspace to '' resets; type 'x' (too short) should abort in-flight 'a'
		input.emit('keypress', '\u007f', { name: 'backspace' });
		input.emit('keypress', 'x', { name: 'x' });
		expect(signals[1].aborted).toBe(true);
		expect(instance.searchTooShort).toBe(true);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual([]);
	});

	test('non-SWR cache hit aborts in-flight fetch', async () => {
		vi.useFakeTimers();
		const signals: AbortSignal[] = [];
		const resolvers = new Map<string, (v: typeof fruits) => void>();
		const resolver = (search: string, opts: { signal: AbortSignal }) => {
			signals.push(opts.signal);
			return new Promise<typeof fruits>((resolve) => {
				resolvers.set(search, resolve);
			});
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			cacheResults: true,
			debounceMs: 10,
		});
		instance.prompt();
		// initial '' fetch
		expect(signals.length).toBe(1);
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(20);
		// 'a' fetch in flight; resolve and cache it
		resolvers.get('a')!([{ value: 'apple', label: 'Apple' }]);
		await Promise.resolve();
		// clear to '' -> cached '' exists -> non-SWR cache hit should abort in-flight (none now)
		// create a new in-flight 'b' fetch then type 'a' (cached)
		input.emit('keypress', '\u007f', { name: 'backspace' });
		input.emit('keypress', 'b', { name: 'b' });
		await vi.advanceTimersByTimeAsync(20);
		const bSignal = signals[signals.length - 1];
		input.emit('keypress', '\u007f', { name: 'backspace' });
		expect(bSignal.aborted).toBe(true);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual(fruits);
	});

	test('new fetch cancels pending min-duration timer', async () => {
		vi.useFakeTimers();
		const resolvers = new Map<string, (v: typeof fruits) => void>();
		const resolver = (search: string) =>
			new Promise<typeof fruits>((resolve) => {
				resolvers.set(search, resolve);
			});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			loadingMinDuration: 100,
			debounceMs: 10,
		});
		instance.prompt();
		// resolve initial fetch; min-duration timer pending
		resolvers.get('')!([{ value: 'apple', label: 'Apple' }]);
		await Promise.resolve();
		expect(instance.loading).toBe(true);
		// type 'a' before min-duration elapses -> new fetch starts, cancels timer
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(10);
		expect(resolvers.has('a')).toBe(true);
		await vi.advanceTimersByTimeAsync(200);
		// min-duration timer for '' must not have applied
		expect(instance.filteredOptions).not.toEqual([{ value: 'apple', label: 'Apple' }]);
	});
});
EOF
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -30