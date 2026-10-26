import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { default as AutocompletePrompt } from '../../src/prompts/autocomplete.js';
import { MockReadable } from '../mock-readable.js';
import { MockWritable } from '../mock-writable.js';

const fruits = [
	{ value: 'apple', label: 'Apple' },
	{ value: 'banana', label: 'Banana' },
	{ value: 'cherry', label: 'Cherry' },
];

describe('AutocompletePrompt async options', () => {
	let input: MockReadable;
	let output: MockWritable;

	beforeEach(() => {
		input = new MockReadable();
		output = new MockWritable();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	test('detects zero-parameter async function and uses first call as first fetch', async () => {
		const calls: string[][] = [];
		const resolver = async () => {
			calls.push([]);
			return fruits;
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});
		expect(instance.loading).toBe(true);
		await Promise.resolve();
		await Promise.resolve();
		expect(calls.length).toBe(1);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual(fruits);
		expect(instance.options).toEqual(fruits);
	});

	test('detects one-parameter async function', async () => {
		const seen: unknown[] = [];
		const resolver = async (search: string) => {
			seen.push(search);
			return fruits.filter((f) => f.label.toLowerCase().includes(search));
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});
		await Promise.resolve();
		expect(seen).toEqual(['']);
		expect(instance.filteredOptions).toEqual(fruits);
	});

	test('resolver receives search and an object with AbortSignal', async () => {
		let received: unknown;
		const resolver = async (_search: string, opts: { signal: AbortSignal }) => {
			received = opts;
			return fruits;
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});
		await Promise.resolve();
		expect(received).toHaveProperty('signal');
		expect((received as { signal: AbortSignal }).signal).toHaveProperty('aborted', false);
		expect(instance.filteredOptions).toEqual(fruits);
	});

	test('does not render during construction', async () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: async () => fruits,
		});
		await Promise.resolve();
		expect(output.buffer).toEqual([]);
		instance.prompt();
		expect(output.buffer.length).toBeGreaterThan(0);
	});

	test('static array still works synchronously', () => {
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: fruits,
		});
		expect(instance.filteredOptions).toEqual(fruits);
		expect(instance.loading).toBe(false);
	});

	test('sync function still works synchronously', () => {
		const fn = vi.fn(function (this: unknown) {
			return fruits;
		});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: fn as never,
		});
		expect(fn).toHaveBeenCalledTimes(1);
		expect(instance.filteredOptions).toEqual(fruits);
		expect(instance.loading).toBe(false);
	});

	test('fetch is debounced and only latest result applies', async () => {
		vi.useFakeTimers();
		const resolvers = new Map<string, (value: typeof fruits) => void>();
		const resolver = (search: string) =>
			new Promise<typeof fruits>((resolve) => {
				resolvers.set(search, resolve);
			});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			debounceMs: 100,
		});
		// initial fetch
		expect(resolvers.has('')).toBe(true);
		instance.prompt();
		input.emit('keypress', 'a', { name: 'a' });
		expect(resolvers.has('a')).toBe(false);
		await vi.advanceTimersByTimeAsync(99);
		expect(resolvers.has('a')).toBe(false);
		await vi.advanceTimersByTimeAsync(1);
		expect(resolvers.has('a')).toBe(true);
		// resolve the older '' fetch; it must be discarded
		resolvers.get('')?.([{ value: 'stale', label: 'Stale' }]);
		await Promise.resolve();
		expect(instance.filteredOptions).toEqual([]);
		// resolve latest 'a' fetch
		resolvers.get('a')?.([{ value: 'apple', label: 'Apple' }]);
		await Promise.resolve();
		expect(instance.filteredOptions).toEqual([{ value: 'apple', label: 'Apple' }]);
		vi.useRealTimers();
	});

	test('cacheResults avoids redundant fetches and clearCache works', async () => {
		let calls = 0;
		const resolver = async (search: string) => {
			calls++;
			return fruits.filter((f) => f.label.toLowerCase().includes(search));
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			cacheResults: true,
		});
		await Promise.resolve();
		expect(calls).toBe(1);
		instance.prompt();
		// type 'a' -> fetch
		input.emit('keypress', 'a', { name: 'a' });
		await new Promise((r) => setTimeout(r, 250));
		expect(calls).toBe(2);
		// clear input -> cached '' from initial fetch, no fetch
		input.emit('keypress', '\u007f', { name: 'backspace' });
		await new Promise((r) => setTimeout(r, 250));
		expect(calls).toBe(2);
		// type 'a' again -> cache hit, no fetch
		input.emit('keypress', 'a', { name: 'a' });
		await new Promise((r) => setTimeout(r, 50));
		expect(calls).toBe(2);
		expect(instance.filteredOptions).toEqual([
			{ value: 'apple', label: 'Apple' },
			{ value: 'banana', label: 'Banana' },
		]);
		// clearCache forces refetch of the next searches
		instance.clearCache();
		input.emit('keypress', '\u007f', { name: 'backspace' });
		await new Promise((r) => setTimeout(r, 250));
		expect(calls).toBe(3);
		input.emit('keypress', 'a', { name: 'a' });
		await new Promise((r) => setTimeout(r, 250));
		expect(calls).toBe(4);
	});

	test('staleWhileRevalidate serves cached immediately and refetches in background', async () => {
		let calls = 0;
		const resolver = async (search: string) => {
			calls++;
			if (search === 'a') {
				return [{ value: 'fresh', label: 'Fresh' }];
			}
			return fruits;
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			cacheResults: true,
			staleWhileRevalidate: true,
		});
		await Promise.resolve();
		instance.prompt();
		input.emit('keypress', 'a', { name: 'a' });
		await new Promise((r) => setTimeout(r, 250));
		expect(instance.filteredOptions).toEqual([{ value: 'fresh', label: 'Fresh' }]);
		expect(calls).toBe(2);
		// clear and re-type 'a' -> should serve cached immediately then refetch
		input.emit('keypress', '\u007f', { name: 'backspace' });
		await new Promise((r) => setTimeout(r, 250));
		input.emit('keypress', 'a', { name: 'a' });
		expect(instance.filteredOptions).toEqual([{ value: 'fresh', label: 'Fresh' }]);
		expect(instance.loading).toBe(true);
		await new Promise((r) => setTimeout(r, 250));
		expect(calls).toBe(4);
		expect(instance.loading).toBe(false);
	});

	test('minSearchLength suppresses fetching and sets searchTooShort; empty always fetches', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const resolver = async (search: string) => {
			calls++;
			return search ? [] : fruits;
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			minSearchLength: 3,
			debounceMs: 10,
		});
		instance.prompt();
		await Promise.resolve();
		expect(calls).toBe(1);
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(1);
		expect(instance.searchTooShort).toBe(true);
		expect(instance.filteredOptions).toEqual([]);
		expect(instance.loading).toBe(false);
		// typing more should fetch
		input.emit('keypress', 'p', { name: 'p' });
		input.emit('keypress', 'p', { name: 'p' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(2);
		expect(instance.searchTooShort).toBe(false);
		vi.useRealTimers();
	});

	test('maxRetries retries and exposes retryCount', async () => {
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
			retryBackoff: 'linear',
		});
		instance.prompt();
		expect(instance.loading).toBe(true);
		await Promise.resolve();
		expect(instance.retryCount).toBe(1);
		expect(instance.loading).toBe(true);
		await vi.advanceTimersByTimeAsync(50);
		await Promise.resolve();
		expect(instance.retryCount).toBe(2);
		await vi.advanceTimersByTimeAsync(50);
		await Promise.resolve();
		expect(instance.retryCount).toBe(0);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual(fruits);
		vi.useRealTimers();
	});

	test('exhausted retries set loadError and fallbackOptions shown', async () => {
		vi.useFakeTimers();
		const resolver = async () => {
			throw new Error('boom');
		};
		const fallback = [{ value: 'fallback', label: 'Fallback' }];
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			maxRetries: 1,
			retryDelay: 10,
			fallbackOptions: fallback,
		});
		instance.prompt();
		await Promise.resolve();
		await vi.advanceTimersByTimeAsync(10);
		await Promise.resolve();
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBe('boom');
		expect(instance.filteredOptions).toEqual(fallback);
		vi.useRealTimers();
	});

	test('AbortError is silently ignored', async () => {
		const resolver = async () => {
			const err = new Error('aborted');
			err.name = 'AbortError';
			throw err;
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});
		await Promise.resolve();
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBeUndefined();
	});

	test('loadingMinDuration keeps loading and defers application', async () => {
		vi.useFakeTimers();
		let resolveFn!: (value: typeof fruits) => void;
		const resolver = () =>
			new Promise<typeof fruits>((resolve) => {
				resolveFn = resolve;
			});
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
			loadingMinDuration: 100,
		});
		instance.prompt();
		resolveFn(fruits);
		await Promise.resolve();
		expect(instance.loading).toBe(true);
		expect(instance.filteredOptions).toEqual([]);
		await vi.advanceTimersByTimeAsync(99);
		expect(instance.loading).toBe(true);
		await vi.advanceTimersByTimeAsync(1);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual(fruits);
		vi.useRealTimers();
	});

	test('submit/cancel resets transient async state and aborts in-flight', async () => {
		let signal: AbortSignal | undefined;
		const resolver = (_search: string, opts: { signal: AbortSignal }) => {
			signal = opts.signal;
			return new Promise<typeof fruits>(() => {});
		};
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: resolver,
		});
		const promise = instance.prompt();
		expect(instance.loading).toBe(true);
		input.emit('keypress', '', { name: 'return' });
		await promise;
		expect(signal?.aborted).toBe(true);
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBeUndefined();
		expect(instance.searchTooShort).toBe(false);
		expect(instance.retryCount).toBe(0);
	});

	test('new fetch aborts previous signal', async () => {
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
			debounceMs: 10,
		});
		instance.prompt();
		expect(signals.length).toBe(1);
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(10);
		expect(signals.length).toBe(2);
		expect(signals[0].aborted).toBe(true);
		vi.useRealTimers();
	});
});

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
		expect(calls).toBe(2); // 'a'
		input.emit('keypress', 'b', { name: 'b' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(3); // 'ab' evicts ''
		// backspace -> input 'a' is cached
		input.emit('keypress', '\u007f', { name: 'backspace' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(3);
		// backspace -> input '' evicted, refetch
		input.emit('keypress', '\u007f', { name: 'backspace' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(4);
		// type 'a' again -> evicted, refetch
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(20);
		expect(calls).toBe(5);
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
		expect(signals.length).toBe(1); // initial ''
		input.emit('keypress', 'a', { name: 'a' });
		input.emit('keypress', 'p', { name: 'p' });
		await vi.advanceTimersByTimeAsync(20);
		expect(signals.length).toBe(2); // 'ap' fetch in flight
		expect(instance.loading).toBe(true);
		// backspace to 'a' (too short) should abort in-flight 'ap'
		input.emit('keypress', '\u007f', { name: 'backspace' });
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
		// initial '' fetch; resolve and cache it
		expect(signals.length).toBe(1);
		resolvers.get('')?.([{ value: 'empty', label: 'Empty' }]);
		await Promise.resolve();
		// type 'a' -> fetch; resolve and cache it
		input.emit('keypress', 'a', { name: 'a' });
		await vi.advanceTimersByTimeAsync(20);
		resolvers.get('a')?.([{ value: 'apple', label: 'Apple' }]);
		await Promise.resolve();
		// backspace -> cached '' hit
		input.emit('keypress', '\u007f', { name: 'backspace' });
		// type 'b' -> in-flight fetch
		input.emit('keypress', 'b', { name: 'b' });
		await vi.advanceTimersByTimeAsync(20);
		const bSignal = signals[signals.length - 1];
		expect(instance.loading).toBe(true);
		// backspace -> cached '' hit should abort in-flight 'b' and apply cache
		input.emit('keypress', '\u007f', { name: 'backspace' });
		expect(bSignal.aborted).toBe(true);
		expect(instance.loading).toBe(false);
		expect(instance.filteredOptions).toEqual([{ value: 'empty', label: 'Empty' }]);
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
		resolvers.get('')?.([{ value: 'apple', label: 'Apple' }]);
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

	test('loading is false during debounce when no fetch is in flight', async () => {
		vi.useFakeTimers();
		const resolver = (search: string) => {
			if (search) {
				return new Promise<typeof fruits>(() => {});
			}
			return Promise.resolve(fruits);
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

	test('loadError is cleared when typing a new search after exhaustion', async () => {
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

	test('synchronous throw keeps loading during loadingMinDuration', async () => {
		vi.useFakeTimers();
		const instance = new AutocompletePrompt({
			input,
			output,
			render: () => 'foo',
			options: () => {
				throw new Error('boom');
			},
			loadingMinDuration: 100,
		});
		instance.prompt();
		expect(instance.loading).toBe(true);
		await vi.advanceTimersByTimeAsync(99);
		expect(instance.loading).toBe(true);
		expect(instance.loadError).toBeUndefined();
		await vi.advanceTimersByTimeAsync(1);
		expect(instance.loading).toBe(false);
		expect(instance.loadError).toBe('boom');
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
		// old '' retry was scheduled for t=100ms; it must not fire
		await vi.advanceTimersByTimeAsync(95);
		expect(searches).toEqual(['', 'a']);
		// 'a' retry (scheduled after its own failure at t=110ms) is allowed to fire
		await vi.advanceTimersByTimeAsync(10);
		expect(searches).toEqual(['', 'a', 'a']);
	});
});

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
