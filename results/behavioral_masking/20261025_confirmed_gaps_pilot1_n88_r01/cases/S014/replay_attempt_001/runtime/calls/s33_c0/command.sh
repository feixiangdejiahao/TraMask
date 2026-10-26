cd /app && cat > packages/prompts/src/autocomplete.ts <<'EOF'
import { styleText } from 'node:util';
import { AutocompletePrompt, settings } from '@clack/core';
import {
	type CommonOptions,
	S_BAR,
	S_BAR_END,
	S_CHECKBOX_INACTIVE,
	S_CHECKBOX_SELECTED,
	S_RADIO_ACTIVE,
	S_RADIO_INACTIVE,
	symbol,
} from './common.js';
import { limitOptions } from './limit-options.js';
import type { Option } from './select.js';

function getLabel<T>(option: Option<T>) {
	return option.label ?? String(option.value ?? '');
}

function getFilteredOption<T>(searchText: string, option: Option<T>): boolean {
	if (!searchText) {
		return true;
	}
	const label = (option.label ?? String(option.value ?? '')).toLowerCase();
	const hint = (option.hint ?? '').toLowerCase();
	const value = String(option.value).toLowerCase();
	const term = searchText.toLowerCase();

	return label.includes(term) || hint.includes(term) || value.includes(term);
}

function getSelectedOptions<T>(values: T[], options: Option<T>[]): Option<T>[] {
	const results: Option<T>[] = [];

	for (const option of options) {
		if (values.includes(option.value)) {
			results.push(option);
		}
	}

	return results;
}

interface AutocompleteSharedOptions<Value> extends CommonOptions {
	/**
	 * The message to display to the user.
	 */
	message: string;
	/**
	 * Available options for the autocomplete prompt. May be a static array, a
	 * synchronous function, or an async resolver that receives the current search
	 * and an AbortSignal and returns the (possibly filtered) options.
	 */
	options:
		| Option<Value>[]
		| ((
				this: AutocompletePrompt<Option<Value>>,
				search: string,
				opts: { signal: AbortSignal }
		  ) => Option<Value>[] | Promise<Option<Value>[]>);
	/**
	 * Maximum number of items to display at once.
	 */
	maxItems?: number;
	/**
	 * Placeholder text to display when no input is provided.
	 */
	placeholder?: string;
	/**
	 * Validates the value
	 */
	validate?: (value: Value | Value[] | undefined) => string | Error | undefined;
	/**
	 * Custom filter function to match options against search input.
	 * If not provided, a default filter that matches label, hint, and value is used.
	 */
	filter?: (search: string, option: Option<Value>) => boolean;
	/**
	 * Delay in milliseconds before an async fetch is triggered after typing stops.
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
	 * Non-empty searches shorter than this value are suppressed.
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
	fallbackOptions?: Option<Value>[];
	/**
	 * Keeps the prompt loading and defers applying results until this many
	 * milliseconds have elapsed since the fetch started.
	 * @default 0
	 */
	loadingMinDuration?: number;
	/**
	 * Message shown while async options are loading.
	 * @default "Loading..."
	 */
	loadingMessage?: string;
	/**
	 * Message shown when no options match the current search.
	 * @default "No matches found"
	 */
	noResultsMessage?: string;
}

export interface AutocompleteOptions<Value> extends AutocompleteSharedOptions<Value> {
	/**
	 * The initial selected value.
	 */
	initialValue?: Value;
	/**
	 * The initial user input
	 */
	initialUserInput?: string;
}

export const autocomplete = <Value>(opts: AutocompleteOptions<Value>) => {
	const prompt = new AutocompletePrompt<Option<Value>>({
		options: opts.options,
		initialValue: opts.initialValue ? [opts.initialValue] : undefined,
		initialUserInput: opts.initialUserInput,
		placeholder: opts.placeholder,
		debounceMs: opts.debounceMs,
		cacheResults: opts.cacheResults,
		maxCacheSize: opts.maxCacheSize,
		minSearchLength: opts.minSearchLength,
		maxRetries: opts.maxRetries,
		retryDelay: opts.retryDelay,
		retryBackoff: opts.retryBackoff,
		staleWhileRevalidate: opts.staleWhileRevalidate,
		fallbackOptions: opts.fallbackOptions,
		loadingMinDuration: opts.loadingMinDuration,
		filter:
			opts.filter ??
			((search: string, opt: Option<Value>) => {
				return getFilteredOption(search, opt);
			}),
		signal: opts.signal,
		input: opts.input,
		output: opts.output,
		validate: opts.validate,
		render() {
			const hasGuide = opts.withGuide ?? settings.withGuide;
			// Title and message display
			const headings = hasGuide
				? [`${styleText('gray', S_BAR)}`, `${symbol(this.state)}  ${opts.message}`]
				: [`${symbol(this.state)}  ${opts.message}`];
			const userInput = this.userInput;
			const options = this.options;
			const placeholder = opts.placeholder;
			const showPlaceholder = userInput === '' && placeholder !== undefined;
			const opt = (option: Option<Value>, state: 'inactive' | 'active' | 'disabled') => {
				const label = getLabel(option);
				const hint =
					option.hint && option.value === this.focusedValue
						? styleText('dim', ` (${option.hint})`)
						: '';
				switch (state) {
					case 'active':
						return `${styleText('green', S_RADIO_ACTIVE)} ${label}${hint}`;
					case 'inactive':
						return `${styleText('dim', S_RADIO_INACTIVE)} ${styleText('dim', label)}`;
					case 'disabled':
						return `${styleText('gray', S_RADIO_INACTIVE)} ${styleText(['strikethrough', 'gray'], label)}`;
				}
			};

			// Handle different states
			switch (this.state) {
				case 'submit': {
					// Show selected value
					const selected = getSelectedOptions(this.selectedValues, options);
					const label =
						selected.length > 0 ? `  ${styleText('dim', selected.map(getLabel).join(', '))}` : '';
					const submitPrefix = hasGuide ? styleText('gray', S_BAR) : '';
					return `${headings.join('\n')}\n${submitPrefix}${label}`;
				}

				case 'cancel': {
					const userInputText = userInput
						? `  ${styleText(['strikethrough', 'dim'], userInput)}`
						: '';
					const cancelPrefix = hasGuide ? styleText('gray', S_BAR) : '';
					return `${headings.join('\n')}\n${cancelPrefix}${userInputText}`;
				}

				default: {
					const barStyle = this.state === 'error' ? 'yellow' : 'cyan';
					const guidePrefix = hasGuide ? `${styleText(barStyle, S_BAR)}  ` : '';
					const guidePrefixEnd = hasGuide ? styleText(barStyle, S_BAR_END) : '';
					// Display cursor position - show plain text in navigation mode
					let searchText = '';
					if (this.isNavigating || showPlaceholder) {
						const searchTextValue = showPlaceholder ? placeholder : userInput;
						searchText = searchTextValue !== '' ? ` ${styleText('dim', searchTextValue)}` : '';
					} else {
						searchText = ` ${this.userInputWithCursor}`;
					}

					const matches =
						this.filteredOptions.length !== options.length
							? styleText(
									'dim',
									` (${this.filteredOptions.length} match${this.filteredOptions.length === 1 ? '' : 'es'})`
								)
							: '';

					// Async status messages
					const minSearchLength = opts.minSearchLength ?? 1;
					const loading = this.loading
						? [`${styleText(barStyle, S_BAR)}  ${styleText('dim', opts.loadingMessage ?? 'Loading...')}`]
						: [];
					const tooShort = this.searchTooShort
						? [
								`${styleText(barStyle, S_BAR)}  ${styleText('yellow', `Type at least ${minSearchLength} characters`)}`,
							]
						: [];
					const fetchError = this.loadError
						? [`${styleText(barStyle, S_BAR)}  ${styleText('red', this.loadError)}`]
						: [];
					const noResults =
						this.filteredOptions.length === 0 &&
						userInput &&
						!this.loading &&
						!this.searchTooShort &&
						!this.loadError
							? [
									`${styleText(barStyle, S_BAR)}  ${styleText('yellow', opts.noResultsMessage ?? 'No matches found')}`,
								]
							: [];

					const errorMessage =
						this.state === 'error'
							? [`${styleText(barStyle, S_BAR)}  ${styleText('yellow', this.error)}`]
							: [];

					const headerLines = [
						...`${headings.join('\n')}${styleText(barStyle, S_BAR)}`.split('\n'),
						`${styleText(barStyle, S_BAR)}  ${styleText('dim', 'Search:')} ${searchText}${matches}`,
						...loading,
						...tooShort,
						...noResults,
						...fetchError,
						...errorMessage,
					];
					const footerLines = [
						`${styleText(barStyle, S_BAR)}  ${['↑/↓ to navigate', 'Tab: select', 'Enter: confirm', 'Type: to search'].join(' • ')}`,
						styleText(barStyle, S_BAR_END),
					];

					// Get limited options for display
					const displayOptions = this.loading
						? []
						: limitOptions({
								cursor: this.cursor,
								options: this.filteredOptions,
								style: opt,
								maxItems: opts.maxItems,
								output: opts.output,
								rowPadding: headerLines.length + footerLines.length,
							});

					return [
						...headerLines,
						...displayOptions.map((option) => `${guidePrefix}${option}`),
						...footerLines,
					].join('\n');
				}
			}
		},
	});

	// Return the result or cancel symbol
	return prompt.prompt() as Promise<Value | symbol>;
};

// Type definition for the autocompleteMultiselect component
export interface AutocompleteMultiSelectOptions<Value> extends AutocompleteSharedOptions<Value> {
	/**
	 * The initial selected values
	 */
	initialValues?: Value[];
	/**
	 * If true, at least one option must be selected
	 */
	required?: boolean;
}

/**
 * Integrated autocomplete multiselect - combines type-ahead filtering with multiselect in one UI
 */
export const autocompleteMultiselect = <Value>(opts: AutocompleteMultiSelectOptions<Value>) => {
	const formatOption = (
		option: Option<Value>,
		active: boolean,
		selectedValues: Value[],
		focusedValue: Value | undefined
	) => {
		const isSelected = selectedValues.includes(option.value);
		const label = option.label ?? String(option.value ?? '');
		const hint =
			option.hint && focusedValue !== undefined && option.value === focusedValue
				? styleText('dim', ` (${option.hint})`)
				: '';
		const checkbox = isSelected
			? styleText('green', S_CHECKBOX_SELECTED)
			: styleText('dim', S_CHECKBOX_INACTIVE);

		if (option.disabled) {
			return `${styleText('gray', S_CHECKBOX_INACTIVE)} ${styleText(['strikethrough', 'gray'], label)}`;
		}
		if (active) {
			return `${checkbox} ${label}${hint}`;
		}
		return `${checkbox} ${styleText('dim', label)}`;
	};

	// Create text prompt which we'll use as foundation
	const prompt = new AutocompletePrompt<Option<Value>>({
		options: opts.options,
		multiple: true,
		placeholder: opts.placeholder,
		debounceMs: opts.debounceMs,
		cacheResults: opts.cacheResults,
		maxCacheSize: opts.maxCacheSize,
		minSearchLength: opts.minSearchLength,
		maxRetries: opts.maxRetries,
		retryDelay: opts.retryDelay,
		retryBackoff: opts.retryBackoff,
		staleWhileRevalidate: opts.staleWhileRevalidate,
		fallbackOptions: opts.fallbackOptions,
		loadingMinDuration: opts.loadingMinDuration,
		filter:
			opts.filter ??
			((search, opt) => {
				return getFilteredOption(search, opt);
			}),
		validate: () => {
			if (opts.required && prompt.selectedValues.length === 0) {
				return 'Please select at least one item';
			}
			return undefined;
		},
		initialValue: opts.initialValues,
		signal: opts.signal,
		input: opts.input,
		output: opts.output,
		render() {
			// Title and symbol
			const title = `${styleText('gray', S_BAR)}\n${symbol(this.state)}  ${opts.message}\n`;

			// Selection counter
			const userInput = this.userInput;
			const placeholder = opts.placeholder;
			const showPlaceholder = userInput === '' && placeholder !== undefined;

			// Search input display
			const searchText =
				this.isNavigating || showPlaceholder
					? styleText('dim', showPlaceholder ? placeholder : userInput) // Just show plain text when in navigation mode
					: this.userInputWithCursor;

			const options = this.options;

			const matches =
				this.filteredOptions.length !== options.length
					? styleText(
							'dim',
							` (${this.filteredOptions.length} match${this.filteredOptions.length === 1 ? '' : 'es'})`
						)
					: '';

			// Render prompt state
			switch (this.state) {
				case 'submit': {
					return `${title}${styleText('gray', S_BAR)}  ${styleText('dim', `${this.selectedValues.length} items selected`)}`;
				}
				case 'cancel': {
					return `${title}${styleText('gray', S_BAR)}  ${styleText(['strikethrough', 'dim'], userInput)}`;
				}
				default: {
					const barStyle = this.state === 'error' ? 'yellow' : 'cyan';
					// Instructions
					const instructions = [
						`${styleText('dim', '↑/↓')} to navigate`,
						`${styleText('dim', this.isNavigating ? 'Space/Tab:' : 'Tab:')} select`,
						`${styleText('dim', 'Enter:')} confirm`,
						`${styleText('dim', 'Type:')} to search`,
					];

					// Async status messages
					const minSearchLength = opts.minSearchLength ?? 1;
					const loading = this.loading
						? [`${styleText(barStyle, S_BAR)}  ${styleText('dim', opts.loadingMessage ?? 'Loading...')}`]
						: [];
					const tooShort = this.searchTooShort
						? [
								`${styleText(barStyle, S_BAR)}  ${styleText('yellow', `Type at least ${minSearchLength} characters`)}`,
							]
						: [];
					const fetchError = this.loadError
						? [`${styleText(barStyle, S_BAR)}  ${styleText('red', this.loadError)}`]
						: [];
					const noResults =
						this.filteredOptions.length === 0 &&
						userInput &&
						!this.loading &&
						!this.searchTooShort &&
						!this.loadError
							? [
									`${styleText(barStyle, S_BAR)}  ${styleText('yellow', opts.noResultsMessage ?? 'No matches found')}`,
								]
							: [];

					const errorMessage =
						this.state === 'error'
							? [`${styleText(barStyle, S_BAR)}  ${styleText('yellow', this.error)}`]
							: [];

					// Calculate header and footer line counts for rowPadding
					const headerLines = [
						...`${title}${styleText(barStyle, S_BAR)}`.split('\n'),
						`${styleText(barStyle, S_BAR)}  ${styleText('dim', 'Search:')} ${searchText}${matches}`,
						...loading,
						...tooShort,
						...noResults,
						...fetchError,
						...errorMessage,
					];
					const footerLines = [
						`${styleText(barStyle, S_BAR)}  ${instructions.join(' • ')}`,
						styleText(barStyle, S_BAR_END),
					];

					// Get limited options for display
					const displayOptions = this.loading
						? []
						: limitOptions({
								cursor: this.cursor,
								options: this.filteredOptions,
								style: (option, active) =>
									formatOption(option, active, this.selectedValues, this.focusedValue),
								maxItems: opts.maxItems,
								output: opts.output,
								rowPadding: headerLines.length + footerLines.length,
							});

					// Build the prompt display
					return [
						...headerLines,
						...displayOptions.map((option) => `${styleText(barStyle, S_BAR)}  ${option}`),
						...footerLines,
					].join('\n');
				}
			}
		},
	});

	// Return the result or cancel symbol
	return prompt.prompt() as Promise<Value[] | symbol>;
};
EOF