cd /app && git add packages/core/src/prompts/autocomplete.ts packages/core/src/prompts/prompt.ts packages/core/test/prompts/autocomplete.test.ts packages/prompts/src/autocomplete.ts packages/prompts/test/autocomplete.test.ts .changeset/async-autocomplete.md && git status --short && git commit -m "feat(core,prompts): add async autocomplete options

Add search-as-you-type support to AutocompletePrompt, autocomplete, and
autocompleteMultiselect. The options resolver may now return a Promise and
receives the search term plus an AbortSignal. Async functions are detected by
invoking them and checking the return value for a .then method, so zero-param
async functions work too. Adds debouncing, result caching with maxCacheSize and
clearCache(), stale-while-revalidate, minSearchLength, retries with linear or
exponential backoff, fallbackOptions, loadingMinDuration, loading/no-results
messages, and proper cleanup on submit/cancel/close."