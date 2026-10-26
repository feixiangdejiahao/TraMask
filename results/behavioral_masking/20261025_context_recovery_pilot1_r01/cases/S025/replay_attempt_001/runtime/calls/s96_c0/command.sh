cd /app && cat > typecheck_test.tmp.ts <<'EOF'
import { autocomplete, autocompleteMultiselect } from './packages/prompts/src/index.js';

autocomplete({
  message: 'x',
  options: async (search, { signal }) => [{ value: 1, label: 'one' }],
});
autocomplete({
  message: 'x',
  options: (search: string) => [{ value: 1, label: 'one' }],
});
autocomplete({
  message: 'x',
  options: async () => [{ value: 1, label: 'one' }],
});
autocompleteMultiselect({
  message: 'x',
  options: async (search, { signal }) => [{ value: 1, label: 'one' }],
  cacheResults: { maxCacheSize: 5 },
  maxCacheSize: 3,
});
EOF
npx tsc --noEmit --strict --module nodenext --moduleResolution nodenext --target es2022 --skipLibCheck typecheck_test.tmp.ts 2>&1 | grep -v 'npm warn' | head -20; echo "DONE"; rm typecheck_test.tmp.ts