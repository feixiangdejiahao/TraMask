cd /app && python3 - <<'PYEOF'
path = 'src/schema/actions/parse/utils.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import type { ExtensionParser, Schema, SchemaUnextendedValue, WriteMode } from '~/schema/index.js'",
    "import type {\n  ExtensionParser,\n  ItemSchema,\n  MapSchema,\n  Schema,\n  SchemaUnextendedValue,\n  WriteMode\n} from '~/schema/index.js'"
)
content = content.replace(
    "  schema: import('~/schema/index.js').ItemSchema | import('~/schema/index.js').MapSchema,",
    "  schema: ItemSchema | MapSchema,"
)
with open(path, 'w') as f:
    f.write(content)
print('done')
PYEOF
npx prettier --write src/schema/actions/parse/utils.ts && npx eslint src/schema/actions/parse/utils.ts 2>&1 | head