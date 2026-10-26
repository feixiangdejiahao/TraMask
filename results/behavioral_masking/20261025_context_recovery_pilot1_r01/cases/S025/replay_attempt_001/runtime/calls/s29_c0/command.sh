cd /app && python3 - <<'PY'
p='packages/prompts/src/autocomplete.ts'
s=open(p).read()

# 1. Replace options type in AutocompleteSharedOptions
old = "\toptions: Option<Value>[] | ((this: AutocompletePrompt<Option<Value>>) => Option<Value>[]);"
new = "\toptions:\n\t\t| Option<Value>[]\n\t\t| ((\n\t\t\t\tthis: AutocompletePrompt<Option<Value>>,\n\t\t\t\tsearch: string,\n\t\t\t\topts: { signal: AbortSignal }\n\t\t  ) => Option<Value>[] | Promise<Option<Value>[]>);"
assert old in s
s=s.replace(old,new)

# 2. Add async options to interface after filter
old = "\tfilter?: (search: string, option: Option<Value>) => boolean;\n}"
new = """\tfilter?: (search: string, option: Option<Value>) => boolean;
\t/**
\t * Time in milliseconds to wait after the user stops typing before fetching results.
\t */
\tdebounceMs?: number;
\t/**
\t * Cache async results by search term to avoid redundant fetches.
\t */
\tcacheResults?: boolean;
\t/**
\t * Maximum number of entries kept in the result cache.
\t */
\tmaxCacheSize?: number;
\t/**
\t * Minimum number of characters required before a non-empty search fetches results.
\t */
\tminSearchLength?: number;
\t/**
\t * Serve cached results immediately while refetching in the background (requires cacheResults).
\t */
\tstaleWhileRevalidate?: boolean;
\t/**
\t * Number of retries attempted after a non-abort failure.
\t */
\tmaxRetries?: number;
\t/**
\t * Base delay in milliseconds between retries.
\t */
\tretryDelay?: number;
\t/**
\t * Retry delay progression: 'linear' or 'exponential'.
\t */
\tretryBackoff?: 'linear' | 'exponential';
\t/**
\t * Options shown when all retries are exhausted and loadError is set.
\t */
\tfallbackOptions?: Option<Value>[];
\t/**
\t * Minimum duration in milliseconds a fetch must be visible as loading.
\t */
\tloadingMinDuration?: number;
\t/**
\t * Message shown while results are loading.
\t */
\tloadingMessage?: string;
\t/**
\t * Message shown when no results match the search.
\t */
\tnoResultsMessage?: string;
}"""
assert old in s
s=s.replace(old,new)

open(p,'w').write(s)
print("done")
PY
nl -ba packages/prompts/src/autocomplete.ts | sed -n '44,120p'