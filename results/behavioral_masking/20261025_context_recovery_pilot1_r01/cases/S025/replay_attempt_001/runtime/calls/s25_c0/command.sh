cat > packages/core/src/prompts/autocomplete.ts <<'EOF'
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

type OptionsFunction<T extends OptionLike> = (
	this: AutocompletePrompt<T>,
	search: string,
	opts: { signal: AbortSignal }
) => T[] | Promise<T[]>;

type OptionsSource<T extends OptionLike> = T[] | OptionsFunction<T>;

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

function isThenable<T>(value: unknown): value is Promise<T> {
	return (
		value !== null &&
		(typeof value === 'object' || typeof value === 'function') &&
		typeof (value as { then?: unknown }).then === 'function'
	);
}

export interface CacheOptions {
	maxCacheSize?: number;
}

export interface AutocompleteOptions<T extends OptionLike>
	extends PromptOptions<T['value'] | T['value'][], AutocompletePrompt<T>> {
	options: OptionsSource<T>;
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
	 * Time in milliseconds to wait after the user stops typing before fetching results.
	 * @default 200
	 */
	debounceMs?: number;
	/**
	 * Cache async results by search term to avoid redundant fetches.
	 */
	cacheResults?: boolean | CacheOptions;
	/**
	 * Minimum number of characters required before a non-empty search fetches results.
	 * @default 0
	 */
	minSearchLength?: number;
	/**
	 * When enabled (requires cacheResults), cached results are shown immediately while a
	 * background refetch keeps the cache and UI fresh.
	 */
	staleWhileRevalidate?: boolean;
	/**
	 * Number of retries attempted after a non-abort failure.
	 * @default 0
	 */
	maxRetries?: number;
	/**
	 * Base delay in milliseconds between retries.
	 * @default 0
	 */
	retryDelay?: number;
	/**
	 * Controls retry delay progression. 'linear' uses a constant delay, 'exponential'
	 * doubles the base delay with each attempt.
	 * @default 'linear'
	 */
	retryBackoff?: 'linear' | 'exponential';
	/**
	 * Options shown when all retries are exhausted and loadError is set.
	 */
	fallbackOptions?: T[];
	/**
	 * Minimum duration in milliseconds a fetch must be visible as loading.
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
	loadError = '';
	searchTooShort = false;
	retryCount = 0;

	focusedValue: T['value'] | undefined;
	#cursor = 0;
	#lastUserInput = '';
	#filterFn: FilterFunction<T>;
	#optionsSource: OptionsSource<T>;
	#options: T[] = [];
	#placeholder: string | undefined;

	#debounceMs: number;
	#minSearchLength: number;
	#maxRetries: number;
	#retryDelay: number;
	#retryBackoff: 'linear' | 'exponential';
	#fallbackOptions: T[] | undefined;
	#loadingMinDuration: number;
	#cache: Map<string, T[]> | undefined;
	#maxCacheSize = Number.POSITIVE_INFINITY;
	#staleWhileRevalidate: boolean;

	#controller: AbortController | undefined;
	#fetchId = 0;
	#fetchStartTime = 0;
	#debounceTimer: ReturnType<typeof setTimeout> | undefined;
	#retryTimer: ReturnType<typeof setTimeout> | undefined;
	#minDurationTimer: ReturnType<typeof setTimeout> | undefined;
	#selectionInitialized = false;
	#initialValue: unknown[] | undefined;
	#isAsync = false;

	get cursor(): number {
		return this.#cursor;
	}

	get userInputWithCursor() {
		if (!this.userInput) {
			return styleText(['inverse', 'hidden'], '_');
		}
		if (this._cursor >= this.userInput.length) {
			return `${this.userInput}▊`;
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

		this.#optionsSource = opts.options;
		this.#placeholder = opts.placeholder;
		this.multiple = opts.multiple === true;
		this.#filterFn = opts.filter ?? defaultFilter;
		this.#debounceMs = opts.debounceMs ?? 200;
		this.#minSearchLength = opts.minSearchLength ?? 0;
		this.#maxRetries = opts.maxRetries ?? 0;
		this.#retryDelay = opts.retryDelay ?? 0;
		this.#retryBackoff = opts.retryBackoff ?? 'linear';
		this.#fallbackOptions = opts.fallbackOptions;
		this.#loadingMinDuration = opts.loadingMinDuration ?? 0;
		this.#staleWhileRevalidate = opts.staleWhileRevalidate === true;
		if (opts.cacheResults) {
			this.#cache = new Map();
			if (typeof opts.cacheResults === 'object') {
				this.#maxCacheSize = opts.cacheResults.maxCacheSize ?? Number.POSITIVE_INFINITY;
			}
		}

		if (opts.initialValue && Array.isArray(opts.initialValue)) {
			if (this.multiple) {
				this.#initialValue = opts.initialValue;
			} else {
				this.#initialValue = opts.initialValue.slice(0, 1);
			}
		}

		if (Array.isArray(this.#optionsSource)) {
			this.#applySyncSource(this.#optionsSource, '');
		} else {
			this.filteredOptions = [];
			// Invoking the resolver now both detects async functions and serves as the
			// first fetch. Its result is applied (never discarded).
			this.#runFetch('', { immediate: true, isInitial: true });
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

	clearCache() {
		this.#cache?.clear();
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

	#onUserInputChanged(value: string): void {
		if (value !== this.#lastUserInput) {
			this.#lastUserInput = value;
			this.#onSearchChange(value);
		}
	}

	#onSearchChange(search: string): void {
		// Non-empty searches shorter than minSearchLength are suppressed.
		if (search && search.length < this.#minSearchLength) {
			this.#invalidateFetch();
			this.searchTooShort = true;
			this.loading = false;
			this.loadError = '';
			this.retryCount = 0;
			this.#options = [];
			this.filteredOptions = [];
			this.#renderIfActive();
			return;
		}

		if (Array.isArray(this.#optionsSource)) {
			this.#applySyncSource(this.#optionsSource, search);
			this.#renderIfActive();
			return;
		}

		// A function that has not yet been detected as async is called synchronously.
		// This preserves the existing synchronous-function behavior.
		if (!this.#isAsync) {
			let result: T[] | Promise<T[]>;
			try {
				result = this.#callSource(search, new AbortController().signal);
			} catch (error) {
				this.#handleFetchError(error as Error, search, this.#fetchId + 1);
				return;
			}
			if (isThenable(result)) {
				this.#isAsync = true;
				this.#onAsyncSearch(search);
				return;
			}
			this.#applySyncSource(result, search);
			this.#renderIfActive();
			return;
		}

		this.#onAsyncSearch(search);
	}

	#onAsyncSearch(search: string): void {
		if (this.#cache) {
			const cached = this.#cache.get(search);
			if (cached !== undefined) {
				if (this.#staleWhileRevalidate) {
					// Serve cached results immediately, then refresh in the background.
					this.loading = true;
					this.#applyAsyncResult(cached, search, { keepLoading: true });
					this.#renderIfActive();
					this.#runFetch(search, { immediate: true });
				} else {
					// Non-stale cache hit invalidates any in-flight fetch.
					this.#invalidateFetch();
					this.#applyAsyncResult(cached, search);
					this.#renderIfActive();
				}
				return;
			}
		}
		this.#runFetch(search);
	}

	#runFetch(
		search: string,
		opts: { immediate?: boolean; isInitial?: boolean; isRetry?: boolean } = {}
	): void {
		if (this.#debounceTimer !== undefined) {
			clearTimeout(this.#debounceTimer);
			this.#debounceTimer = undefined;
		}

		if (!opts.immediate) {
			this.#debounceTimer = setTimeout(() => {
				this.#debounceTimer = undefined;
				this.#runFetch(search, { immediate: true });
			}, this.#debounceMs);
			return;
		}

		this.#invalidateFetch();
		this.#cancelMinDurationTimer();
		this.#cancelRetryTimer();
		if (!opts.isRetry) {
			this.retryCount = 0;
		}

		const fetchId = this.#fetchId;
		const controller = new AbortController();
		this.#controller = controller;
		this.#fetchStartTime = Date.now();
		this.loading = true;
		this.loadError = '';
		this.searchTooShort = false;

		let result: T[] | Promise<T[]>;
		try {
			result = this.#callSource(search, controller.signal);
		} catch (error) {
			this.#handleFetchError(error as Error, search, fetchId);
			return;
		}

		this.#isAsync = isThenable(result);
		if (this.#isAsync) {
			Promise.resolve(result).then(
				(options) => this.#handleFetchSuccess(options as T[], search, fetchId, true),
				(error) => this.#handleFetchError(error as Error, search, fetchId)
			);
		} else {
			this.#handleFetchSuccess(result as T[], search, fetchId, false);
		}
	}

	#callSource(search: string, signal: AbortSignal): T[] | Promise<T[]> {
		return (this.#optionsSource as OptionsFunction<T>).call(this, search, { signal });
	}

	#handleFetchSuccess(options: T[], search: string, fetchId: number, deferOutcome: boolean): void {
		if (fetchId !== this.#fetchId) {
			return;
		}
		this.#controller = undefined;

		const apply = () => {
			if (fetchId !== this.#fetchId) {
				return;
			}
			this.#applyAsyncResult(options, search);
			this.#renderIfActive();
		};

		if (deferOutcome) {
			this.#scheduleOutcome(apply);
		} else {
			apply();
		}
	}

	#handleFetchError(error: Error, search: string, fetchId: number): void {
		if (fetchId !== this.#fetchId) {
			return;
		}

		if (error.name === 'AbortError') {
			this.#controller = undefined;
			this.loading = false;
			this.#renderIfActive();
			return;
		}

		if (this.retryCount < this.#maxRetries) {
			this.retryCount++;
			const delay =
				this.#retryBackoff === 'exponential'
					? this.#retryDelay * 2 ** (this.retryCount - 1)
					: this.#retryDelay;
			this.#retryTimer = setTimeout(() => {
				this.#retryTimer = undefined;
				this.#runFetch(search, { immediate: true, isRetry: true });
			}, delay);
			// Keep loading true while retrying.
			return;
		}

		this.#controller = undefined;
		const apply = () => {
			if (fetchId !== this.#fetchId) {
				return;
			}
			this.loadError = error instanceof Error ? error.message : String(error);
			this.loading = false;
			this.filteredOptions = this.#fallbackOptions ? [...this.#fallbackOptions] : [];
			this.#options = [...this.filteredOptions];
			this.#renderIfActive();
		};
		this.#scheduleOutcome(apply);
	}

	#applySyncSource(source: T[], search: string): void {
		this.#options = [...source];
		this.filteredOptions = search
			? source.filter((opt) => this.#filterFn(search, opt))
			: [...source];
		this.loading = false;
		this.loadError = '';
		this.searchTooShort = false;
		this.retryCount = 0;
		this.#initializeSelection(this.#options);
		this.#updateSelection();
	}

	#applyAsyncResult(options: T[], search: string, opts: { keepLoading?: boolean } = {}): void {
		this.#options = [...options];
		this.filteredOptions = [...options];
		this.#initializeSelection(this.#options);
		if (!opts.keepLoading) {
			this.loading = false;
		}
		this.loadError = '';
		this.searchTooShort = false;
		this.retryCount = 0;
		if (this.#cache) {
			this.#cache.set(search, options);
			this.#trimCache();
		}
		this.#updateSelection();
	}

	#initializeSelection(options: T[]): void {
		if (this.#selectionInitialized) {
			return;
		}
		this.#selectionInitialized = true;

		if (this.#initialValue) {
			for (const selectedValue of this.#initialValue) {
				const selectedIndex = options.findIndex((opt) => opt.value === selectedValue);
				if (selectedIndex !== -1) {
					this.toggleSelected(selectedValue);
					this.#cursor = selectedIndex;
				}
			}
		} else if (!this.multiple && options.length > 0) {
			this.toggleSelected(options[0].value);
			this.#cursor = 0;
		}

		this.focusedValue = options[this.#cursor]?.value;
	}

	#updateSelection(): void {
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

	#scheduleOutcome(apply: () => void): void {
		const elapsed = Date.now() - this.#fetchStartTime;
		const remaining = this.#loadingMinDuration - elapsed;
		if (remaining > 0) {
			this.#minDurationTimer = setTimeout(() => {
				this.#minDurationTimer = undefined;
				apply();
			}, remaining);
		} else {
			apply();
		}
	}

	#invalidateFetch(): void {
		if (this.#controller) {
			this.#controller.abort();
			this.#controller = undefined;
		}
		this.#fetchId++;
	}

	#cancelMinDurationTimer(): void {
		if (this.#minDurationTimer !== undefined) {
			clearTimeout(this.#minDurationTimer);
			this.#minDurationTimer = undefined;
		}
	}

	#cancelRetryTimer(): void {
		if (this.#retryTimer !== undefined) {
			clearTimeout(this.#retryTimer);
			this.#retryTimer = undefined;
		}
	}

	#renderIfActive(): void {
		if (this.state !== 'initial') {
			this.render();
		}
	}

	protected override close(): void {
		// Abort in-flight work, clear timers, and reset transient async state.
		this.#invalidateFetch();
		this.#cancelMinDurationTimer();
		this.#cancelRetryTimer();
		if (this.#debounceTimer !== undefined) {
			clearTimeout(this.#debounceTimer);
			this.#debounceTimer = undefined;
		}
		this.loading = false;
		this.loadError = '';
		this.searchTooShort = false;
		this.retryCount = 0;
		super.close();
	}
}
EOF
cd /app/packages/core && npx tsc --noEmit --project ../../tsconfig.json 2>&1 | head -40