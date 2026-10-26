cd /app && python3 - <<'PYEOF'
for path in ['src/schema/actions/jsonSchemer/formattedValue/item.ts', 'src/schema/actions/jsonSchemer/formattedValue/map.ts']:
    with open(path) as f:
        content = f.read()
    # Remove type addition block
    content = content.replace(
        "  } & ([REQUIRED_PROPERTIES] extends [never] ? {} : { required: REQUIRED_PROPERTIES[] }) & {\n    if?: RequiredIfJSONSchemas extends { if: infer IF } ? IF : never\n    then?: RequiredIfJSONSchemas extends { then: infer THEN } ? THEN : never\n    allOf?: RequiredIfJSONSchemas extends { allOf: infer ALL_OF } ? ALL_OF : never\n  }\n>",
        "  } & ([REQUIRED_PROPERTIES] extends [never] ? {} : { required: REQUIRED_PROPERTIES[] })\n>"
    )
    # Remove unused type import (keep getRequiredIfJSONSchema import)
    content = content.replace(
        "import type { RequiredIfJSONSchemas, RequiredProperties } from './shared.js'\nimport { getRequiredIfJSONSchema } from './shared.js'",
        "import type { RequiredProperties } from './shared.js'\nimport { getRequiredIfJSONSchema } from './shared.js'"
    )
    with open(path, 'w') as f:
        f.write(content)
    print(path, 'patched')
PYEOF
npx tsc --noEmit 2>&1 | head -30