cd /app && cat > packages/core/test/typecheck.tmp.ts <<'EOF'
import { AutocompletePrompt } from '@clack/core';
import { autocomplete, autocompleteMultiselect } from '@clack/prompts';

interface Fruit { value: string; label?: string; disabled?: boolean; }

new AutocompletePrompt<Fruit>({ render: () => 'x', options: [{ value: 'a' }] });
new AutocompletePrompt<Fruit>({
  render: () => 'x',
  options: function (this: AutocompletePrompt<Fruit>) {
    return [{ value: 'a' }];
  },
});
new AutocompletePrompt<Fruit>({
  render: () => 'x',
  options: (search, { signal }) => Promise.resolve([{ value: search + signal.aborted }]),
  debounceMs: 100,
  cacheResults: true,
  maxCacheSize: 5,
  minSearchLength: 2,
  maxRetries: 1,
  retryDelay: 10,
  retryBackoff: 'exponential',
  staleWhileRevalidate: true,
  fallbackOptions: [{ value: 'fb' }],
  loadingMinDuration: 50,
});

autocomplete({ message: 'x', options: [{ value: 'a', label: 'A' }] });
autocomplete({ message: 'x', options: function (this: any) { return [{ value: 'a', label: 'A' }]; } });
autocomplete({
  message: 'x',
  options: async (search, { signal }) => [{ value: search + signal.aborted, label: search }],
  loadingMessage: 'Loading',
  noResultsMessage: 'None',
  debounceMs: 200,
});
autocompleteMultiselect({
  message: 'x',
  options: async (search) => [{ value: search, label: search }],
  minSearchLength: 3,
});
EOF
npx tsc --noEmit -p packages/core/tsconfig.json 2>&1 | grep -v "npm warn" | head -20; rm -f packages/core/test/typecheck.tmp.ts