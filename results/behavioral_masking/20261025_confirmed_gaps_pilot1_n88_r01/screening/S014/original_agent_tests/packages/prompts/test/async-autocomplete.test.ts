import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { autocomplete, autocompleteMultiselect } from '../src/autocomplete.js';
import { MockReadable, MockWritable } from './test-utils.js';

describe('async autocomplete wrappers', () => {
	let input: MockReadable;
	let output: MockWritable;

	beforeEach(() => {
		input = new MockReadable();
		output = new MockWritable();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	test('shows custom loading message while fetching', async () => {
		let resolveFn!: (value: Array<{ value: string; label: string }>) => void;
		const result = autocomplete({
			message: 'Pick',
			options: () =>
				new Promise<Array<{ value: string; label: string }>>((resolve) => {
					resolveFn = resolve;
				}),
			loadingMessage: 'Fetching...',
			input,
			output,
		});
		await Promise.resolve();
		expect(output.buffer.join('')).toContain('Fetching...');
		resolveFn([{ value: 'apple', label: 'Apple' }]);
		await Promise.resolve();
		input.emit('keypress', '', { name: 'return' });
		await result;
	});

	test('honors noResultsMessage override', async () => {
		const result = autocomplete({
			message: 'Pick',
			options: async (search: string) => {
				if (!search) return [{ value: 'apple', label: 'Apple' }];
				return [];
			},
			noResultsMessage: 'Nothing here',
			input,
			output,
		});
		await Promise.resolve();
		input.emit('keypress', 'z', { name: 'z' });
		await new Promise((r) => setTimeout(r, 250));
		expect(output.buffer.join('')).toContain('Nothing here');
		expect(output.buffer.join('')).not.toContain('No matches found');
		input.emit('keypress', '', { name: 'return' });
		await result;
	});

	test('shows "Type at least N characters" when too short', async () => {
		const resolver = vi.fn(async (search: string) => {
			return search ? [] : [{ value: 'apple', label: 'Apple' }];
		});
		const result = autocomplete({
			message: 'Pick',
			options: resolver,
			minSearchLength: 3,
			input,
			output,
		});
		await Promise.resolve();
		const callsAfterInit = resolver.mock.calls.length;
		input.emit('keypress', 'a', { name: 'a' });
		await new Promise((r) => setTimeout(r, 250));
		expect(resolver.mock.calls.length).toBe(callsAfterInit);
		expect(output.buffer.join('')).toContain('Type at least 3 characters');
		input.emit('keypress', '', { name: 'return' });
		await result;
	});

	test('passes through async options and fetches on typed search', async () => {
		const resolver = vi.fn(async (search: string, _opts: { signal: AbortSignal }) => {
			const all = [
				{ value: 'apple', label: 'Apple' },
				{ value: 'banana', label: 'Banana' },
			];
			if (!search) return all;
			return all.filter((o) => o.label.toLowerCase().includes(search));
		});
		const result = autocomplete({
			message: 'Pick',
			options: resolver,
			debounceMs: 50,
			input,
			output,
		});
		await Promise.resolve();
		expect(resolver.mock.calls[0][0]).toBe('');
		expect(resolver.mock.calls[0][1]).toHaveProperty('signal');
		input.emit('keypress', 'a', { name: 'a' });
		await new Promise((r) => setTimeout(r, 120));
		expect(resolver.mock.calls.some((call) => call[0] === 'a')).toBe(true);
		input.emit('keypress', '', { name: 'return' });
		await result;
	});

	test('autocompleteMultiselect shows too-short message', async () => {
		const resolver = vi.fn(async (search: string) => {
			return search ? [] : [{ value: 'apple', label: 'Apple' }];
		});
		const result = autocompleteMultiselect({
			message: 'Pick',
			options: resolver,
			minSearchLength: 2,
			input,
			output,
		});
		await Promise.resolve();
		const callsAfterInit = resolver.mock.calls.length;
		input.emit('keypress', 'a', { name: 'a' });
		await new Promise((r) => setTimeout(r, 250));
		expect(resolver.mock.calls.length).toBe(callsAfterInit);
		expect(output.buffer.join('')).toContain('Type at least 2 characters');
		input.emit('keypress', '', { name: 'return' });
		await result;
	});
});
