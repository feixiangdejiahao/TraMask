cd /app && cat > packages/core/src/prompts/autocomplete.ts <<'EOF'
import type { Key } from 'node:readline';
import { styleText } from 'node:util';
import { findCursor } from '../utils/cursor.js';
import Prompt, { type PromptOptions } from './prompt.js';

interface OptionLike {
	value: unknown;
	label?: string;
	disabled?: boolean;
}

type FilterFunction<T extends OptionLike> = (search: string, opt: T) => boolean;

export type AutocompleteResolver<T extends OptionLike> = (
	this: AutocompletePrompt<T>,
	search: string,
	opts: { signal: AbortSignal }
) => T[] | Promise<T[]>;

type Options<T extends OptionLike> = T[] | AutocompleteResolver<T>;

function getCursorForValue<T extends OptionLike>(
	selected: T['value'] | undefined,
	items: T[]
): number {
	if (selected === undefined) {
		return 0;
	}

	const currLength = items.length;

	// If filtering changed the available options, update cursor
	if (currLength === 0) {
		return 0;
	}

	// Try to maintain the same selected item
	const index = items.findIndex((item) => item.value === selected);
	return index !== -1 ? index : 0;
}

function defaultFilter<T extends OptionLike>(input: string, option: T): boolean {
	const label = option.label ?? String(option.value);
	return label.toLowerCase().includes(input.toLowerCase());
}

function normalisedValue<T>(multiple: boolean, values: T[] | undefined): T | T[] | undefined {
	if (!values) {
		return undefined;
	}
	if (multiple) {
		return values;
	}
	return values[0];
}

function isThenable<T>(value: T[] | Promise<T[]> | Thenable<T[]>): value is Promise<T[]> {
	return typeof (value as { then?: unknown })?.then === 'function';
}

export interface AutocompleteOptions<T extends OptionLike>
	extends PromptOptions<T['value'] | T['value'][], AutocompletePrompt<T>> {
	options: Options<T>;
	filter?: FilterFunction<T>;
	multiple?: boolean;
	/**
	 * When set (non-empty), pressing Tab with no input fills the field with this value
	 * and runs the normal filter/selection logic so the user can confirm with Enter.
	 * Tab only fills the input when the placeholder matches at least one option under
	 * the prompt's filter (so the value remains selectable).
	 */
	placeholder?: string;
	/**
	 * Delay in milliseconds before an async fetch is triggered after the user stops typing.
	 * @default 200
	 */
	debounceMs?: number;
	/**
	 * Enables caching of async results keyed by search term.
	 * @default false
	 */
	cacheResults?: boolean;
	/**
	 * Maximum number of cached search results to retain.
	 * @default 100
	 */
	maxCacheSize?: number;
	/**
	 * Non-empty searches shorter than this value are suppressed and show a "type more" hint.
	 * Empty searches always fetch.
	 * @default 1
	 */
	minSearchLength?: number;
	/**
	 * Serves cached results immediately while refetching in the background.
	 * Requires `cacheResults`.
	 * @default false
	 */
	staleWhileRevalidate?: boolean;
	/**
	 * Number of retry attempts after a failed async fetch.
	 * @default 0
	 */
	maxRetries?: number;
	/**
	 * Base delay in milliseconds before retrying a failed fetch.
	 * @default 0
	 */
	retryDelay?: number;
	/**
	 * Controls retry delay progression.
	 * @default 'linear'
	 */
	retryBackoff?: 'linear' | 'exponential';
	/**
	 * Options shown when all retries are exhausted and `loadError` is set.
	 */
	fallbackOptions?: T[];
	/**
	 * Keeps the prompt loading and defers applying results until this many milliseconds
	 * have elapsed since the fetch started.
	 * @default 0
	 */
	loadingMinDuration?: number;
}

export default class AutocompletePrompt<T extends OptionLike> extends Prompt<
	T['value'] | T['value'][]
> {
	filteredOptions: T[];
	multiple: boolean;
	isNavigating = false;
	selectedValues: Array<T['value']> = [];
	loading = false;
	loadError: string | undefined;
	searchTooShort = false;
	retryCount = 0;

	focusedValue: T['value'] | undefined;
	#cursor = 0;
	#lastUserInput = '';
	#filterFn: FilterFunction<T>;
	#resolver: AutocompleteResolver<T>;
	#options: T[];
	#isAsync = false;
	#placeholder: string | undefined;
	#initialValue: unknown[] | undefined;
	#debounceMs: number;
	#minSearchLength: number;
	#cacheResults: boolean;
	#maxCacheSize: number;
	#staleWhileRevalidate: boolean;
	#maxRetries: number;
	#retryDelay: number;
	#retryBackoff: 'linear' | 'exponential';
	#fallbackOptions: T[] | undefined;
	#loadingMinDuration: number;
	#cache = new Map<string, T[]>();
	#abortController: AbortController | undefined;
	#debounceTimer: ReturnType<typeof setTimeout> | undefined;
	#minDurationTimer: ReturnType<typeof setTimeout> | undefined;
	#retryTimer: ReturnType<typeof setTimeout> | undefined;
	#fetchId = 0;
	#fetchStartTime = 0;
	#initialised = false;

	get cursor(): number {
		return this.#cursor;
	}

	get userInputWithCursor() {
		if (!this.userInput) {
			return styleText(['inverse', 'hidden'], '_');
		}
		if (this._cursor >= this.userInput.length) {
			return `${this.userInput}▉`;
		}
		const s1 = this.userInput.slice(0, this._cursor);
		const [s2, ...s3] = this.userInput.slice(this._cursor);
		return `${s1}${styleText('inverse', s2)}${s3.join('')}`;
	}

	get options(): T[] {
		return this.#options;
	}

	constructor(opts: AutocompleteOptions<T>) {
		super(opts);

		this.#placeholder = opts.placeholder;
		this.#filterFn = opts.filter ?? defaultFilter;
		this.#debounceMs = opts.debounceMs ?? 200;
		this.#minSearchLength = opts.minSearchLength ?? 1;
		this.#cacheResults = opts.cacheResults ?? false;
		this.#maxCacheSize = opts.maxCacheSize ?? 100;
		this.#staleWhileRevalidate = opts.staleWhileRevalidate ?? false;
		this.#maxRetries = opts.maxRetries ?? 0;
		this.#retryDelay = opts.retryDelay ?? 0;
		this.#retryBackoff = opts.retryBackoff ?? 'linear';
		this.#fallbackOptions = opts.fallbackOptions;
		this.#loadingMinDuration = opts.loadingMinDuration ?? 0;
		this.#initialValue = Array.isArray(opts.initialValue) ? opts.initialValue : undefined;
		this.multiple = opts.multiple === true;

		if (Array.isArray(opts.options)) {
			const options = opts.options;
			this.#resolver = function (_search: string) {
				return options;
			};
			this.#options = options;
			this.filteredOptions = [...options];
			this.#setupInitialValues();
		} else {
			this.#resolver = opts.options;
			this.#options = [];
			this.filteredOptions = [];
			// The first invocation doubles as async detection: if the return value is
			// thenable the resolver is asynchronous and this result is the first fetch.
			this.#startFetch('');
		}

		this.on('key', (char, key) => this.#onKey(char, key));
		this.on('userInput', (value) => this.#onUserInputChanged(value));
	}

	protected override _isActionKey(char: string | undefined, key: Key): boolean {
		return (
			char === '\t' ||
			(this.multiple &&
				this.isNavigating &&
				key.name === 'space' &&
				char !== undefined &&
				char !== '')
		);
	}

	#onKey(_char: string | undefined, key: Key): void {
		const isUpKey = key.name === 'up';
		const isDownKey = key.name === 'down';
		const isReturnKey = key.name === 'return';

		// Tab with empty input and placeholder: fill input with placeholder to trigger autocomplete
		// Only when the placeholder matches at least one (non-disabled) option so the value remains selectable
		const isEmptyOrOnlyTab = this.userInput === '' || this.userInput === '\t';
		const placeholder = this.#placeholder;
		const options = this.options;
		const placeholderMatchesOption =
			placeholder !== undefined &&
			placeholder !== '' &&
			options.some((opt) => !opt.disabled && this.#filterFn(placeholder, opt));
		if (key.name === 'tab' && isEmptyOrOnlyTab && placeholderMatchesOption) {
			if (this.userInput === '\t') {
				this._clearUserInput();
			}
			this._setUserInput(placeholder, true);
			this.isNavigating = false;
			return;
		}

		// Start navigation mode with up/down arrows
		if (isUpKey || isDownKey) {
			this.#cursor = findCursor(this.#cursor, isUpKey ? -1 : 1, this.filteredOptions);
			this.focusedValue = this.filteredOptions[this.#cursor]?.value;
			if (!this.multiple) {
				this.selectedValues = [this.focusedValue];
			}
			this.isNavigating = true;
		} else if (isReturnKey) {
			this.value = normalisedValue(this.multiple, this.selectedValues);
		} else {
			if (this.multiple) {
				if (
					this.focusedValue !== undefined &&
					(key.name === 'tab' || (this.isNavigating && key.name === 'space'))
				) {
					this.toggleSelected(this.focusedValue);
				} else {
					this.isNavigating = false;
				}
			} else {
				if (this.focusedValue) {
					this.selectedValues = [this.focusedValue];
				}
				this.isNavigating = false;
			}
		}
	}

	deselectAll() {
		this.selectedValues = [];
	}

	toggleSelected(value: T['value']) {
		if (this.filteredOptions.length === 0) {
			return;
		}

		if (this.multiple) {
			if (this.selectedValues.includes(value)) {
				this.selectedValues = this.selectedValues.filter((v) => v !== value);
			} else {
				this.selectedValues = [...this.selectedValues, value];
			}
		} else {
			this.selectedValues = [value];
		}
	}

	clearCache() {
		this.#cache.clear();
	}

	#onUserInputChanged(value: string): void {
		if (value === this.#lastUserInput) {
			return;
		}
		this.#lastUserInput = value;

		if (!this.#isAsync) {
			this.#fetchSync(value);
			return;
		}

		if (value !== '' && value.length < this.#minSearchLength) {
			this.searchTooShort = true;
			this.loadError = undefined;
			this.filteredOptions = [];
			this.#invalidateInFlight();
			this.#updateCursorAndSelection();
			this.#renderIfActive();
			return;
		}

		this.searchTooShort = false;

		if (this.#cacheResults) {
			const cached = this.#cache.get(value);
			if (cached !== undefined) {
				if (!this.#staleWhileRevalidate) {
					// Non-SWR cache hit: apply immediately and invalidate any in-flight fetch.
					this.#invalidateInFlight();
					this.loading = false;
					this.loadError = undefined;
					this.retryCount = 0;
					this.#options = cached;
					this.filteredOptions = cached;
					this.#updateCursorAndSelection();
					this.#renderIfActive();
					return;
				}
				// SWR: serve cached immediately, then refetch in the background.
				this.#options = cached;
				this.filteredOptions = cached;
				this.#updateCursorAndSelection();
				this.#renderIfActive();
				this.#startFetch(value);
				return;
			}
		}

		this.#scheduleDebouncedFetch(value);
	}

	#fetchSync(search: string): void {
		const id = ++this.#fetchId;
		const options = this.#resolver.call(this, search, { signal: undefined as unknown as AbortSignal });
		this.#options = options;
		this.filteredOptions = this.#filterOptions(options, search);
		this.#updateCursorAndSelection();
		this.#setupInitialValues();
		if (id !== this.#fetchId) {
			return;
		}
		this.#renderIfActive();
	}

	#scheduleDebouncedFetch(search: string): void {
		this.#clearDebounceTimer();
		this.#debounceTimer = setTimeout(() => {
			this.#debounceTimer = undefined;
			this.#startFetch(search);
		}, this.#debounceMs);
	}

	#startFetch(search: string): void {
		this.#clearTimers();
		this.#abortCurrentFetch();

		const id = ++this.#fetchId;
		const controller = new AbortController();
		this.#abortController = controller;
		const startTime = Date.now();
		this.#fetchStartTime = startTime;

		let result: T[] | Promise<T[]>;
		try {
			result = this.#resolver.call(this, search, { signal: controller.signal });
		} catch (err) {
			this.#handleFetchFailure(id, search, err as Error, startTime);
			return;
		}

		if (isThenable(result)) {
			this.#isAsync = true;
			this.loading = true;
			Promise.resolve(result).then(
				(options) => this.#handleFetchSuccess(id, search, options, startTime),
				(err) => this.#handleFetchFailure(id, search, err as Error, startTime)
			);
		} else {
			if (this.#isAsync) {
				this.#handleFetchSuccess(id, search, result, startTime);
			} else {
				this.#options = result;
				this.filteredOptions = this.#filterOptions(result, search);
				this.#updateCursorAndSelection();
				this.#setupInitialValues();
				this.#renderIfActive();
			}
		}
	}

	#handleFetchSuccess(id: number, search: string, options: T[], startTime: number): void {
		if (id !== this.#fetchId || search !== this.#lastUserInput) {
			return;
		}

		this.#setCache(search, options);

		const apply = () => {
			if (id !== this.#fetchId || search !== this.#lastUserInput) {
				return;
			}
			this.#clearMinDurationTimer();
			this.#abortController = undefined;
			this.loading = false;
			this.loadError = undefined;
			this.retryCount = 0;
			this.#options = options;
			this.filteredOptions = this.#isAsync ? options : this.#filterOptions(options, search);
			this.#updateCursorAndSelection();
			this.#setupInitialValues();
			this.#renderIfActive();
		};

		if (this.#loadingMinDuration > 0) {
			const remaining = this.#loadingMinDuration - (Date.now() - startTime);
			if (remaining > 0) {
				this.#clearMinDurationTimer();
				this.#minDurationTimer = setTimeout(apply, remaining);
				return;
			}
		}
		apply();
	}

	#handleFetchFailure(id: number, search: string, err: Error, startTime: number): void {
		if (id !== this.#fetchId || search !== this.#lastUserInput) {
			return;
		}

		if (err?.name === 'AbortError') {
			this.loading = false;
			return;
		}

		this.loadError = err instanceof Error ? err.message : String(err);
		this.retryCount += 1;

		if (this.retryCount <= this.#maxRetries) {
			const delay = this.#getRetryDelay(this.retryCount);
			this.#clearRetryTimer();
			this.#retryTimer = setTimeout(() => {
				this.#retryTimer = undefined;
				this.#startFetch(search);
			}, delay);
			// Loading stays true while retrying.
			return;
		}

		this.loading = false;
		if (this.#fallbackOptions) {
			this.#options = [...this.#fallbackOptions];
			this.filteredOptions = [...this.#fallbackOptions];
		} else {
			this.filteredOptions = [];
		}
		this.#updateCursorAndSelection();
		this.#renderIfActive();
	}

	#getRetryDelay(attempt: number): number {
		if (this.#retryBackoff === 'exponential') {
			return this.#retryDelay * 2 ** (attempt - 1);
		}
		return this.#retryDelay;
	}

	#filterOptions(options: T[], search: string): T[] {
		if (search) {
			return options.filter((opt) => this.#filterFn(search, opt));
		}
		return [...options];
	}

	#updateCursorAndSelection(): void {
		const valueCursor = getCursorForValue(this.focusedValue, this.filteredOptions);
		this.#cursor = findCursor(valueCursor, 0, this.filteredOptions);
		const focusedOption = this.filteredOptions[this.#cursor];
		if (focusedOption && !focusedOption.disabled) {
			this.focusedValue = focusedOption.value;
		} else {
			this.focusedValue = undefined;
		}
		if (!this.multiple) {
			if (this.focusedValue !== undefined) {
				this.toggleSelected(this.focusedValue);
			} else {
				this.deselectAll();
			}
		}
	}

	#setupInitialValues(): void {
		if (this.#initialised) {
			return;
		}
		this.#initialised = true;

		const options = this.#options;
		let initialValues: unknown[] | undefined;
		if (this.#initialValue && Array.isArray(this.#initialValue)) {
			if (this.multiple) {
				initialValues = this.#initialValue;
			} else {
				initialValues = this.#initialValue.slice(0, 1);
			}
		} else {
			if (!this.multiple && options.length > 0) {
				initialValues = [options[0].value];
			}
		}

		if (initialValues) {
			for (const selectedValue of initialValues) {
				const selectedIndex = options.findIndex((opt) => opt.value === selectedValue);
				if (selectedIndex !== -1) {
					this.toggleSelected(selectedValue);
					this.#cursor = selectedIndex;
				}
			}
		}

		this.focusedValue = options[this.#cursor]?.value;
	}

	#invalidateInFlight(): void {
		this.#abortCurrentFetch();
		this.#fetchId += 1;
		this.#clearTimers();
		this.loading = false;
	}

	#setCache(search: string, options: T[]): void {
		if (!this.#cacheResults) {
			return;
		}
		this.#cache.set(search, options);
		if (this.#cache.size > this.#maxCacheSize) {
			const firstKey = this.#cache.keys().next().value;
			if (firstKey !== undefined) {
				this.#cache.delete(firstKey);
			}
		}
	}

	#clearDebounceTimer(): void {
		if (this.#debounceTimer !== undefined) {
			clearTimeout(this.#debounceTimer);
			this.#debounceTimer = undefined;
		}
	}

	#clearMinDurationTimer(): void {
		if (this.#minDurationTimer !== undefined) {
			clearTimeout(this.#minDurationTimer);
			this.#minDurationTimer = undefined;
		}
	}

	#clearRetryTimer(): void {
		if (this.#retryTimer !== undefined) {
			clearTimeout(this.#retryTimer);
			this.#retryTimer = undefined;
		}
	}

	#clearTimers(): void {
		this.#clearDebounceTimer();
		this.#clearMinDurationTimer();
		this.#clearRetryTimer();
	}

	#abortCurrentFetch(): void {
		this.#abortController?.abort();
		this.#abortController = undefined;
	}

	#renderIfActive(): void {
		if (this.state === 'initial') {
			return;
		}
		this.render();
	}

	protected override close() {
		this.#clearTimers();
		this.#abortCurrentFetch();
		this.#fetchId += 1;
		this.loading = false;
		this.loadError = undefined;
		this.searchTooShort = false;
		this.retryCount = 0;
		super.close();
	}
}
EOF