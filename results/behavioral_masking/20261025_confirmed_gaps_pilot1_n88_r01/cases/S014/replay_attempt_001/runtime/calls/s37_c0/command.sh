cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
s=open(p).read()

# 1. options type + async options in interface
old = '''\toptions: Option<Value>[] | ((this: AutocompletePrompt<Option<Value>>) => Option<Value>[]);
\t/**
\t * Maximum number of items to display at once.
\t */
\tmaxItems?: number;'''
new = '''\toptions:
\t\t| Option<Value>[]
\t\t| ((
\t\t\t\tthis: AutocompletePrompt<Option<Value>>,
\t\t\t\tsearch: string,
\t\t\t\topts: { signal: AbortSignal }
\t\t  ) => Option<Value>[] | Promise<Option<Value>[]>);
\t/**
\t * Maximum number of items to display at once.
\t */
\tmaxItems?: number;'''
assert old in s
s=s.replace(old,new)

old = '''\tfilter?: (search: string, option: Option<Value>) => boolean;
}

export interface AutocompleteOptions<Value> extends AutocompleteSharedOptions<Value> {'''
new = '''\tfilter?: (search: string, option: Option<Value>) => boolean;
\t/**
\t * Delay in milliseconds before an async fetch is triggered after typing stops.
\t * @default 200
\t */
\tdebounceMs?: number;
\t/**
\t * Enables caching of async results keyed by search term.
\t * @default false
\t */
\tcacheResults?: boolean;
\t/**
\t * Maximum number of cached search results to retain.
\t * @default 100
\t */
\tmaxCacheSize?: number;
\t/**
\t * Non-empty searches shorter than this value are suppressed.
\t * Empty searches always fetch.
\t * @default 1
\t */
\tminSearchLength?: number;
\t/**
\t * Serves cached results immediately while refetching in the background.
\t * Requires `cacheResults`.
\t * @default false
\t */
\tstaleWhileRevalidate?: boolean;
\t/**
\t * Number of retry attempts after a failed async fetch.
\t * @default 0
\t */
\tmaxRetries?: number;
\t/**
\t * Base delay in milliseconds before retrying a failed fetch.
\t * @default 0
\t */
\tretryDelay?: number;
\t/**
\t * Controls retry delay progression.
\t * @default 'linear'
\t */
\tretryBackoff?: 'linear' | 'exponential';
\t/**
\t * Options shown when all retries are exhausted and `loadError` is set.
\t */
\tfallbackOptions?: Option<Value>[];
\t/**
\t * Keeps the prompt loading and defers applying results until this many
\t * milliseconds have elapsed since the fetch started.
\t * @default 0
\t */
\tloadingMinDuration?: number;
\t/**
\t * Message shown while async options are loading.
\t * @default "Loading..."
\t */
\tloadingMessage?: string;
\t/**
\t * Message shown when no options match the current search.
\t * @default "No matches found"
\t */
\tnoResultsMessage?: string;
}

export interface AutocompleteOptions<Value> extends AutocompleteSharedOptions<Value> {'''
assert old in s
s=s.replace(old,new)

# 2. pass-through in autocomplete()
old = '''\tconst prompt = new AutocompletePrompt({
\t\toptions: opts.options,
\t\tinitialValue: opts.initialValue ? [opts.initialValue] : undefined,
\t\tinitialUserInput: opts.initialUserInput,
\t\tplaceholder: opts.placeholder,
\t\tfilter:'''
new = '''\tconst prompt = new AutocompletePrompt<Option<Value>>({
\t\toptions: opts.options,
\t\tinitialValue: opts.initialValue ? [opts.initialValue] : undefined,
\t\tinitialUserInput: opts.initialUserInput,
\t\tplaceholder: opts.placeholder,
\t\tdebounceMs: opts.debounceMs,
\t\tcacheResults: opts.cacheResults,
\t\tmaxCacheSize: opts.maxCacheSize,
\t\tminSearchLength: opts.minSearchLength,
\t\tmaxRetries: opts.maxRetries,
\t\tretryDelay: opts.retryDelay,
\t\tretryBackoff: opts.retryBackoff,
\t\tstaleWhileRevalidate: opts.staleWhileRevalidate,
\t\tfallbackOptions: opts.fallbackOptions,
\t\tloadingMinDuration: opts.loadingMinDuration,
\t\tfilter:'''
assert old in s
s=s.replace(old,new)

# 3. pass-through in autocompleteMultiselect()
old = '''\tconst prompt = new AutocompletePrompt<Option<Value>>({
\t\toptions: opts.options,
\t\tmultiple: true,
\t\tplaceholder: opts.placeholder,
\t\tfilter:'''
new = '''\tconst prompt = new AutocompletePrompt<Option<Value>>({
\t\toptions: opts.options,
\t\tmultiple: true,
\t\tplaceholder: opts.placeholder,
\t\tdebounceMs: opts.debounceMs,
\t\tcacheResults: opts.cacheResults,
\t\tmaxCacheSize: opts.maxCacheSize,
\t\tminSearchLength: opts.minSearchLength,
\t\tmaxRetries: opts.maxRetries,
\t\tretryDelay: opts.retryDelay,
\t\tretryBackoff: opts.retryBackoff,
\t\tstaleWhileRevalidate: opts.staleWhileRevalidate,
\t\tfallbackOptions: opts.fallbackOptions,
\t\tloadingMinDuration: opts.loadingMinDuration,
\t\tfilter:'''
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("part1 done")
PY