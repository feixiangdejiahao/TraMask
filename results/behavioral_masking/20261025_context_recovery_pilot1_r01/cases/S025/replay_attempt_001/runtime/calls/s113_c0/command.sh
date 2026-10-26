cd /app && git config user.email "dev@example.com" && git config user.name "Dev" && git commit -m "feat(core,prompts): add async autocomplete options

Add search-as-you-type support to AutocompletePrompt, autocomplete, and
autocompleteMultiselect. The options resolver may now return a Promise and
receives the search term plus an AbortSignal. Async functions are detected by
invoking them and checking the return value for a .then method, so zero-param
async functions work too. Adds debouncing, result caching with maxCacheSize and
clearCache(), stale-while-revalidate, minSearchLength, retries with linear or
exponential backoff, fallbackOptions, loadingMinDuration, loading/no-results
messages, and proper cleanup on submit/cancel/close."