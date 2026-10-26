cd /app && python3 - <<'PY'
p='packages/core/test/prompts/async-autocomplete.test.ts'
s=open(p).read()

# Rewrite maxCacheSize test
old_start = "test('maxCacheSize evicts oldest entries', async () => {"
old_end = "\ttest('exponential backoff doubles delay', async () => {"
i=s.index(old_start)
j=s.index(old_end)
old = s[i:j]
new = '''test('maxCacheSize evicts oldest entries', async () => {
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
		expect(calls).toBe(2); // 'a'
		input.emit('keypress', 'b', { name: 'b' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(3); // 'ab' evicts ''
		// backspace -> input 'a' is cached
		input.emit('keypress', '\\u007f', { name: 'backspace' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(3);
		// backspace -> input '' evicted, refetch
		input.emit('keypress', '\\u007f', { name: 'backspace' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(4);
		// type 'a' again -> evicted, refetch
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(5);
	});

'''
s = s[:i] + new + s[j:]

# Rewrite searchTooShort abort test
old_start = "test('entering searchTooShort aborts in-flight fetch', async () => {"
old_end = "\ttest('non-SWR cache hit aborts in-flight fetch', async () => {"
i=s.index(old_start)
j=s.index(old_end)
old = s[i:j]
new = '''test('entering searchTooShort aborts in-flight fetch', async () => {
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
		expect(signals.length).toBe(1); // initial ''
		input.emit('keypress', 'a', { name: 'a' });
		input.emit('keypress', 'p', { name: 'p' });
		await vi.advanceTimersByTimeAsync(20);
		expect(signals.length).toBe(2); // 'ap' fetch in flight
		expect(instance.loading).toBe(true);
		// backspace to 'a' (too short) should abort in-flight 'ap'
		input.emit('keypress', '\\u007f', { name: 'backspace' });
		expect(signals[1].aborted).toBe(true);
		expect(instance.searchTooShort).toBe(true);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual([]);
	});

'''
s = s[:i] + new + s[j:]

# Rewrite non-SWR cache hit abort test
old_start = "test('non-SWR cache hit aborts in-flight fetch', async () => {"
old_end = "\ttest('new fetch cancels pending min-duration timer', async () => {"
i=s.index(old_start)
j=s.index(old_end)
old = s[i:j]
new = '''test('non-SWR cache hit aborts in-flight fetch', async () => {
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
		// backspace -> cached '' hit
		input.emit('keypress', '\\u007f', { name: 'backspace' });
		// type 'b' -> in-flight fetch
		input.emit('keypress', 'b', { name: 'b' });
		await vi.advanceTimersByTimeAsync(20);
		const bSignal = signals[signals.length - 1];
		expect(instance.loading).toBe(true);
		// backspace -> cached '' hit should abort in-flight 'b' and apply cache
		input.emit('keypress', '\\u007f', { name: 'backspace' });
		expect(bSignal.aborted).toBe(true);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual(fruits);
	});

'''
s = s[:i] + new + s[j:]

open(p,'w').write(s)
print("tests rewritten")
PY
cd /app/packages/core && npx vitest run test/prompts/async-autocomplete.test.ts 2>&1 | tail -25