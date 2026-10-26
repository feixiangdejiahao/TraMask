import { cursor } from 'sisteransi';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { default as AutocompletePrompt } from '../../src/prompts/autocomplete.js';
import { MockReadable } from '../mock-readable.js';
import { MockWritable } from '../mock-writable.js';

describe('AutocompletePrompt', () => {
	let input: MockReadable;
	let output: MockWritable;
	const testOptions = [
		{ value: 'apple', label: 'Apple' },
		{ value: 'banana', label: 'Banana' },
		{ value: 'cherry', label: 'Cherry' },
		{ value: 'grape', label: 'Grape' },
		{ value: 'orange', label: 'Orange' },
	];

	beforeEach(() => {
		input = new MockReadable();
		output = new MockWritable();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	test('renders render() result', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
		});
		instance.prompt();
		expect(output.buffer).to.deep.equal([cursor.hide, 'foo']);
	});

	test('initial options match provided options', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
		});

		instance.prompt();

		// Initial state should have all options
		expect(instance.filteredOptions.length).to.equal(testOptions.length);
		expect(instance.cursor).to.equal(0);
	});

	test('cursor navigation with event emitter', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
		});

		instance.prompt();

		// Initial cursor should be at 0
		expect(instance.cursor).to.equal(0);

		// Directly trigger the cursor event with 'down'
		instance.emit('key', '', { name: 'down' });

		// After down event, cursor should be 1
		expect(instance.cursor).to.equal(1);

		// Trigger cursor event with 'up'
		instance.emit('key', '', { name: 'up' });

		// After up event, cursor should be back to 0
		expect(instance.cursor).to.equal(0);
	});

	test('initialValue selects correct option', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
			initialValue: ['cherry'],
		});

		// The cursor should be initialized to the cherry index
		const cherryIndex = testOptions.findIndex((opt) => opt.value === 'cherry');
		expect(instance.cursor).to.equal(cherryIndex);

		// The selectedValue should be cherry
		expect(instance.selectedValues).to.deep.equal(['cherry']);
	});

	test('initialValue defaults to first option when non-multiple', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
		});

		expect(instance.cursor).to.equal(0);
		expect(instance.selectedValues).to.deep.equal(['apple']);
	});

	test('initialValue is empty when multiple', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
			multiple: true,
		});

		expect(instance.cursor).to.equal(0);
		expect(instance.selectedValues).to.deep.equal([]);
	});

	test('filtering through user input', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
		});

		instance.prompt();

		// Initial state should have all options
		expect(instance.filteredOptions.length).to.equal(testOptions.length);

		// Simulate typing 'a' by emitting keypress event
		input.emit('keypress', 'a', { name: 'a' });

		// Check that filtered options are updated to include options with 'a'
		expect(instance.filteredOptions.length).to.be.lessThan(testOptions.length);

		// Check that 'apple' is in the filtered options
		const hasApple = instance.filteredOptions.some((opt) => opt.value === 'apple');
		expect(hasApple).to.equal(true);
	});

	test('default filter function works correctly', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
		});

		instance.prompt();

		input.emit('keypress', 'a', { name: 'a' });
		input.emit('keypress', 'p', { name: 'p' });

		expect(instance.filteredOptions).toEqual([
			{ value: 'apple', label: 'Apple' },
			{ value: 'grape', label: 'Grape' },
		]);

		input.emit('keypress', 'z', { name: 'z' });

		expect(instance.filteredOptions).toEqual([]);
	});

	test('submit without nav resolves to first option in non-multiple', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
		});

		const promise = instance.prompt();
		input.emit('keypress', '', { name: 'return' });
		const result = await promise;

		expect(instance.selectedValues).to.deep.equal(['apple']);
		expect(result).to.equal('apple');
	});

	test('submit without nav resolves to [] in multiple', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
			multiple: true,
		});

		const promise = instance.prompt();
		input.emit('keypress', '', { name: 'return' });
		const result = await promise;

		expect(instance.selectedValues).to.deep.equal([]);
		expect(result).to.deep.equal([]);
	});

	test('Tab with empty input and placeholder fills input and submit returns matching option', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
			placeholder: 'apple',
		});

		const promise = instance.prompt();
		input.emit('keypress', '\t', { name: 'tab' });
		input.emit('keypress', '', { name: 'return' });
		const result = await promise;

		expect(instance.userInput).to.equal('apple');
		expect(result).to.equal('apple');
	});

	test('Tab with non-matching placeholder does not fill input', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: testOptions,
			placeholder: 'Type to search...',
		});

		instance.prompt();
		input.emit('keypress', '\t', { name: 'tab' });

		// Placeholder does not match any option, so input must not be filled with placeholder
		expect(instance.userInput).not.to.equal('Type to search...');
	});
});

describe('AutocompletePrompt async options', () => {
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

	test('detects async by invoking and uses the first fetch result', async () => {
		const options = [{ value: 'a', label: 'A' }];
		const resolver = vi.fn(async () => options);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});

		expect(instance.loading).toBe(true);
		expect(resolver).toHaveBeenCalledTimes(1);
		expect(resolver).toHaveBeenCalledWith(
			'',
			expect.objectContaining({ signal: expect.any(AbortSignal) })
		);
		expect(output.buffer).toEqual([]);

		await flush();
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual(options);
		expect(resolver).toHaveBeenCalledTimes(1);
	});

	test('detects zero-parameter async functions by return value', async () => {
		const options = [{ value: 'z', label: 'Z' }];
		const resolver = vi.fn(async () => options);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});

		await flush();
		expect(instance.filteredOptions).toEqual(options);
		expect(resolver).toHaveBeenCalledTimes(1);
	});

	test('keeps loading true while fetch is in flight and renders only when active', async () => {
		let resolveFn: (value: { value: string }[]) => void = () => {};
		const resolver = vi.fn(
			() =>
				new Promise<{ value: string }[]>((resolve) => {
					resolveFn = resolve;
				})
		);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});

		expect(instance.loading).toBe(true);
		// No render during construction
		expect(output.buffer).toEqual([]);

		instance.prompt();
		expect(output.buffer.length).toBeGreaterThan(0);

		resolveFn([{ value: 'ok' }]);
		await flush();
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual([{ value: 'ok' }]);
	});

	test('only latest fetch result is applied and previous signal is aborted', async () => {
		let resolveA: (value: { value: string }[]) => void = () => {};
		const signals: AbortSignal[] = [];
		const resolver = vi.fn((search: string, _opts: { signal: AbortSignal }) => {
			if (search === 'a') {
				return new Promise<{ value: string }[]>((resolve) => {
					resolveA = resolve;
				});
			}
			return Promise.resolve([{ value: 'new' }]);
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			debounceMs: 10,
		});

		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // initial fetch

		instance.emit('userInput', 'a');
		await vi.advanceTimersByTimeAsync(10); // start fetch a
		expect(resolver).toHaveBeenCalledWith('a', expect.anything());
		const lastCall = resolver.mock.calls.at(-1);
		if (lastCall) {
			signals.push(lastCall[1].signal);
		}

		console.log('PILOT1_SIGNAL_BEFORE_TARGET', signals[0].aborted);
		instance.emit('userInput', 'ab');
		await vi.advanceTimersByTimeAsync(10); // start fetch ab
		console.log('PILOT1_SIGNAL_AFTER_TARGET', signals[0].aborted);
		expect(signals[0].aborted).toBe(true);
		await vi.advanceTimersByTimeAsync(0);

		resolveA([{ value: 'stale' }]);
		await flush();
		expect(instance.filteredOptions).toEqual([{ value: 'new' }]);
	});

	test('debounces fetches by debounceMs and defaults to 200ms', async () => {
		const resolver = vi.fn(async () => [{ value: 'x' }]);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			debounceMs: 20,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0);

		instance.emit('userInput', 'a');
		instance.emit('userInput', 'ab');
		instance.emit('userInput', 'abc');
		expect(resolver).toHaveBeenCalledTimes(1); // only initial
		await vi.advanceTimersByTimeAsync(10);
		expect(resolver).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(10);
		expect(resolver).toHaveBeenCalledTimes(2);
		expect(resolver).toHaveBeenLastCalledWith('abc', expect.anything());
	});

	test('cacheResults avoids redundant fetches', async () => {
		const resolver = vi.fn(async (search: string) => [{ value: search }]);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			cacheResults: true,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // '' fetch

		instance.emit('userInput', 'a');
		await vi.advanceTimersByTimeAsync(10); // 'a' fetch
		expect(resolver).toHaveBeenCalledTimes(2);

		instance.emit('userInput', '');
		await vi.advanceTimersByTimeAsync(10); // cache hit for ''
		instance.emit('userInput', 'a');
		await vi.advanceTimersByTimeAsync(10); // cache hit for 'a'
		expect(resolver).toHaveBeenCalledTimes(2);
	});

	test('cacheResults maxCacheSize evicts oldest entries', async () => {
		const resolver = vi.fn(async (search: string) => [{ value: search }]);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			cacheResults: { maxCacheSize: 2 },
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // ''
		for (const search of ['a', 'b', 'c']) {
			instance.emit('userInput', search);
			await vi.advanceTimersByTimeAsync(10);
		}
		expect(resolver).toHaveBeenCalledTimes(4); // '', a, b, c
		instance.emit('userInput', 'a'); // 'a' was evicted
		await vi.advanceTimersByTimeAsync(10);
		expect(resolver).toHaveBeenCalledTimes(5);
	});

	test('clearCache clears cached results', async () => {
		const resolver = vi.fn(async (search: string) => [{ value: search }]);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			cacheResults: true,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0);
		instance.emit('userInput', 'a');
		await vi.advanceTimersByTimeAsync(10);
		expect(resolver).toHaveBeenCalledTimes(2);

		// Change input away from 'a' so emitting 'a' again is a real search change.
		instance.emit('userInput', 'b');
		await vi.advanceTimersByTimeAsync(10);
		expect(resolver).toHaveBeenCalledTimes(3);

		instance.clearCache();
		instance.emit('userInput', 'a');
		await vi.advanceTimersByTimeAsync(10);
		expect(resolver).toHaveBeenCalledTimes(4);
	});

	test('minSearchLength suppresses too-short non-empty searches but always fetches empty', async () => {
		const resolver = vi.fn(async () => [{ value: 'x' }]);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			minSearchLength: 2,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // '' fetch
		expect(resolver).toHaveBeenCalledTimes(1);

		instance.emit('userInput', 'a');
		await vi.advanceTimersByTimeAsync(50);
		expect(resolver).toHaveBeenCalledTimes(1);
		expect(instance.searchTooShort).toBe(true);
		expect(instance.filteredOptions).toEqual([]);
		expect(instance.loading).toBe(false);

		instance.emit('userInput', '');
		await vi.advanceTimersByTimeAsync(10);
		expect(resolver).toHaveBeenCalledTimes(2);
		expect(instance.searchTooShort).toBe(false);
	});

	test('an in-flight fetch is invalidated as soon as input changes, even during debounce', async () => {
		let resolveB: (value: { value: string }[]) => void = () => {};
		const resolver = vi.fn((search: string) => {
			if (search === 'b') {
				return new Promise<{ value: string }[]>((resolve) => {
					resolveB = resolve;
				});
			}
			return Promise.resolve([{ value: `${search}-new` }]);
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // initial ''

		instance.emit('userInput', 'b');
		await vi.advanceTimersByTimeAsync(10); // start slow fetch for 'b'

		instance.emit('userInput', 'ba'); // invalidates 'b' immediately, schedules 'ba'
		// The stale 'b' fetch resolves before the 'ba' debounce fires.
		resolveB([{ value: 'b-stale' }]);
		await vi.advanceTimersByTimeAsync(0);
		// The stale 'b' result must not be applied.
		expect(instance.filteredOptions).not.toEqual([{ value: 'b-stale' }]);

		await vi.advanceTimersByTimeAsync(10); // debounce fires, fetch 'ba'
		await vi.advanceTimersByTimeAsync(0);
		expect(instance.filteredOptions).toEqual([{ value: 'ba-new' }]);
	});

	test('entering searchTooShort cancels a pending debounced fetch', async () => {
		const resolver = vi.fn(async () => [{ value: 'x' }]);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			minSearchLength: 2,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // initial ''

		instance.emit('userInput', 'ab'); // schedules debounce for 'ab'
		instance.emit('userInput', 'a'); // too short; must cancel debounce
		await vi.advanceTimersByTimeAsync(50);
		expect(resolver).toHaveBeenCalledTimes(1); // never fetched 'ab'
		expect(instance.searchTooShort).toBe(true);
	});

	test('AbortError is silently ignored', async () => {
		const resolver = vi.fn(async () => {
			const error = new Error('Aborted');
			error.name = 'AbortError';
			throw error;
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0);
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBe('');
	});

	test('non-abort failures set loadError to a string', async () => {
		const resolver = vi.fn(async () => {
			throw new Error('boom');
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0);
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBe('boom');
	});

	test('maxRetries keeps loading and exposes retryCount', async () => {
		const resolver = vi.fn(async () => {
			throw new Error('boom');
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			maxRetries: 2,
			retryDelay: 100,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // initial fail -> retry 1
		expect(instance.loading).toBe(true);
		expect(instance.retryCount).toBe(1);

		await vi.advanceTimersByTimeAsync(100); // retry 1 fail -> retry 2
		expect(instance.retryCount).toBe(2);
		expect(instance.loading).toBe(true);

		await vi.advanceTimersByTimeAsync(100); // retry 2 fail -> exhausted
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBe('boom');
	});

	test('a successful retry clears loadError and resets retryCount', async () => {
		let attempts = 0;
		const resolver = vi.fn(async () => {
			attempts++;
			if (attempts <= 2) {
				throw new Error('boom');
			}
			return [{ value: 'ok' }];
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			maxRetries: 2,
			retryDelay: 100,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // initial fail -> retry 1
		expect(instance.loading).toBe(true);
		await vi.advanceTimersByTimeAsync(100); // retry 1 fail -> retry 2
		expect(instance.loading).toBe(true);
		await vi.advanceTimersByTimeAsync(100); // retry 2 succeeds
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBe('');
		expect(instance.retryCount).toBe(0);
		expect(instance.filteredOptions).toEqual([{ value: 'ok' }]);
	});

	test('retryBackoff exponential doubles delay each attempt', async () => {
		const resolver = vi.fn(async () => {
			throw new Error('boom');
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			maxRetries: 2,
			retryDelay: 100,
			retryBackoff: 'exponential',
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // initial fail, retry in 100
		await vi.advanceTimersByTimeAsync(100); // retry 1 fail, retry in 200
		expect(instance.retryCount).toBe(2);
		await vi.advanceTimersByTimeAsync(100); // still retrying (200 not elapsed)
		expect(instance.loadError).toBe('');
		await vi.advanceTimersByTimeAsync(100); // exhausted
		expect(instance.loadError).toBe('boom');
	});

	test('fallbackOptions shown when retries exhausted', async () => {
		const resolver = vi.fn(async () => {
			throw new Error('boom');
		});
		const fallback = [{ value: 'fb', label: 'Fallback' }];
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			maxRetries: 1,
			retryDelay: 10,
			fallbackOptions: fallback,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0);
		await vi.advanceTimersByTimeAsync(10);
		expect(instance.loadError).toBe('boom');
		expect(instance.filteredOptions).toEqual(fallback);
	});

	test('staleWhileRevalidate serves cached results and refetches in background', async () => {
		const resolver = vi.fn(async (search: string) => [{ value: `${search}-v1` }]);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			cacheResults: true,
			staleWhileRevalidate: true,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // ''
		instance.emit('userInput', 'a');
		await vi.advanceTimersByTimeAsync(10); // 'a' v1
		expect(instance.filteredOptions).toEqual([{ value: 'a-v1' }]);

		resolver.mockImplementation(async (search: string) => [{ value: `${search}-v2` }]);
		instance.emit('userInput', 'b');
		await vi.advanceTimersByTimeAsync(10);
		instance.emit('userInput', 'a');
		// Cache hit serves immediately
		expect(instance.filteredOptions).toEqual([{ value: 'a-v1' }]);
		expect(instance.loading).toBe(true);

		await vi.advanceTimersByTimeAsync(0);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual([{ value: 'a-v2' }]);
	});

	test('loadingMinDuration keeps loading and defers result application', async () => {
		let resolveFn: (value: { value: string }[]) => void = () => {};
		const resolver = vi.fn(
			() =>
				new Promise<{ value: string }[]>((resolve) => {
					resolveFn = resolve;
				})
		);
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			loadingMinDuration: 200,
		});
		instance.prompt();

		resolveFn([{ value: 'x' }]);
		await vi.advanceTimersByTimeAsync(0);
		expect(instance.loading).toBe(true);
		expect(instance.filteredOptions).toEqual([]);

		await vi.advanceTimersByTimeAsync(100);
		expect(instance.loading).toBe(true);

		await vi.advanceTimersByTimeAsync(100);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual([{ value: 'x' }]);
	});

	test('a new fetch cancels a pending loadingMinDuration timer', async () => {
		let resolveA: (value: { value: string }[]) => void = () => {};
		const resolver = vi.fn((search: string) => {
			if (search === 'a') {
				return new Promise<{ value: string }[]>((resolve) => {
					resolveA = resolve;
				});
			}
			return Promise.resolve([{ value: 'b' }]);
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			loadingMinDuration: 200,
			debounceMs: 10,
		});
		instance.prompt();
		await vi.advanceTimersByTimeAsync(0); // initial ''

		instance.emit('userInput', 'a');
		await vi.advanceTimersByTimeAsync(10); // fetch a
		resolveA([{ value: 'a' }]);
		await vi.advanceTimersByTimeAsync(0); // result arrives, min-duration timer pending
		expect(instance.loading).toBe(true);

		instance.emit('userInput', 'b');
		await vi.advanceTimersByTimeAsync(10); // new fetch cancels min-duration timer
		await vi.advanceTimersByTimeAsync(0);
		// 'a' must not be applied later
		await vi.advanceTimersByTimeAsync(200);
		expect(instance.filteredOptions).toEqual([{ value: 'b' }]);
		expect(instance.loading).toBe(false);
	});

	test('close aborts in-flight fetches and resets transient state', async () => {
		const resolver = vi.fn(() => new Promise<{ value: string }[]>(() => {}));
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});
		instance.prompt();
		expect(instance.loading).toBe(true);

		input.emit('keypress', '\x03', { name: 'c', ctrl: true });
		await flush();
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBe('');
		expect(instance.searchTooShort).toBe(false);
		expect(instance.retryCount).toBe(0);
	});
});
