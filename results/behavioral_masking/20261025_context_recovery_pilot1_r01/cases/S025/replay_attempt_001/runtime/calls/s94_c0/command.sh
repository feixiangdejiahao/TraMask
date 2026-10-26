cd /app && cat > /tmp/typecheck_test.ts <<'EOF'
import { autocomplete, autocompleteMultiselect } from './packages/prompts/src/index.js';

autocomplete({
  message: 'x',
  options: async (search, { signal }) => [{ value: 1 }],
});
autocomplete({
  message: 'x',
  options: (search: string) => [{ value: 1 }],
});
autocomplete({
  message: 'x',
  options: async () => [{ value: 1 }],
});
autocompleteMultiselect({
  message: 'x',
  options: async (search, { signal }) => [{ value: 1 }],
  cacheResults: { maxCacheSize: 5 },
  maxCacheSize: 3,
});
EOF
npx tsc --noEmit --strict --module nodenext --moduleResolution nodenext --target es2022 --skipLibCheck /tmp/typecheck_test.ts 2>&1 | head -20 && echo "TYPECHECK OK"