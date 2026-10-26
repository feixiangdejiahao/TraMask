cd /app && cat > /tmp/typecheck.ts <<'EOF'
import { AutocompletePrompt } from '@clack/core';
import { autocomplete, autocompleteMultiselect } from '@clack/prompts';

interface Fruit { value: string; label?: string; disabled?: boolean; }

// Old static array
new AutocompletePrompt<Fruit>({ render: () => 'x', options: [{ value: 'a' }] });

// Old sync function with `this`
const a = new AutocompletePrompt<Fruit>({
  render: () => 'x',
  options: function (this: AutocompletePrompt<Fruit>) {
    return [{ value: 'a' }];
  },
});

// New async resolver with search + signal
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

// Wrapper old form
autocomplete({ message: 'x', options: [{ value: 'a' }] });
autocomplete({ message: 'x', options: function (this: any) { return [{ value: 'a' }]; } });
autocomplete({
  message: 'x',
  options: async (search, { signal }) => [{ value: search + signal.aborted }],
  loadingMessage: 'Loading',
  noResultsMessage: 'None',
  debounceMs: 200,
});
autocompleteMultiselect({
  message: 'x',
  options: async (search) => [{ value: search }],
  minSearchLength: 3,
});

a.clearCache();
EOF
cd /app && npx tsc --noEmit --strict --module node16 --moduleResolution node16 --target es2022 --lib es2022 --types node /tmp/typecheck.ts 2>&1 | grep -v "npm warn" | head -30