cd /app && python3 - <<'PYEOF'
# item formatter
path = 'src/schema/actions/zodSchemer/formatter/item.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import { withAttributeNameDecoding } from './utils.js'",
    "import { withAttributeNameDecoding, withRequiredIf } from './utils.js'"
)
content = content.replace(
    "    z.object(\n      Object.fromEntries(\n        displayedAttrEntries.map(([attributeName, attribute]) => [\n          attributeName,\n          schemaZodFormatter(attribute, { ...options, defined: false })\n        ])\n      )\n    )\n  ) as",
    "    withRequiredIf(\n      schema,\n      z.object(\n        Object.fromEntries(\n          displayedAttrEntries.map(([attributeName, attribute]) => [\n            attributeName,\n            schemaZodFormatter(attribute, { ...options, defined: false })\n          ])\n        )\n      )\n    )\n  ) as"
)
with open(path, 'w') as f:
    f.write(content)
print("item formatter done")

# map formatter
path = 'src/schema/actions/zodSchemer/formatter/map.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import { withAttributeNameDecoding, withOptional } from './utils.js'",
    "import { withAttributeNameDecoding, withOptional, withRequiredIf } from './utils.js'"
)
content = content.replace(
    "        withValidate(\n          schema,\n          z.object(\n            Object.fromEntries(\n              displayedAttrEntries.map(([attributeName, attribute]) => [\n                attributeName,\n                schemaZodFormatter(attribute, { ...options, defined: false })\n              ])\n            )\n          )\n        )",
    "        withValidate(\n          schema,\n          withRequiredIf(\n            schema,\n            z.object(\n              Object.fromEntries(\n                displayedAttrEntries.map(([attributeName, attribute]) => [\n                  attributeName,\n                  schemaZodFormatter(attribute, { ...options, defined: false })\n                ])\n              )\n            )\n          )\n        )"
)
with open(path, 'w') as f:
    f.write(content)
print("map formatter done")

# item parser
path = 'src/schema/actions/zodSchemer/parser/item.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import { withAttributeNameEncoding } from './utils.js'",
    "import { withAttributeNameEncoding, withRequiredIf } from './utils.js'"
)
content = content.replace(
    "    z.object(\n      Object.fromEntries(\n        displayedAttrEntries.map(([attributeName, attribute]) => [\n          attributeName,\n          schemaZodParser(attribute, { ...options, defined: false })\n        ])\n      )\n    )\n  ) as",
    "    withRequiredIf(\n      schema,\n      options,\n      z.object(\n        Object.fromEntries(\n          displayedAttrEntries.map(([attributeName, attribute]) => [\n            attributeName,\n            schemaZodParser(attribute, { ...options, defined: false })\n          ])\n        )\n      )\n    )\n  ) as"
)
with open(path, 'w') as f:
    f.write(content)
print("item parser done")

# map parser
path = 'src/schema/actions/zodSchemer/parser/map.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import { withAttributeNameEncoding, withDefault, withOptional } from './utils.js'",
    "import { withAttributeNameEncoding, withDefault, withOptional, withRequiredIf } from './utils.js'"
)
content = content.replace(
    "        withValidate(\n          schema,\n          z.object(\n            Object.fromEntries(\n              displayedAttrEntries.map(([attributeName, attribute]) => [\n                attributeName,\n                schemaZodParser(attribute, { ...options, defined: false })\n              ])\n            )\n          )\n        )",
    "        withValidate(\n          schema,\n          withRequiredIf(\n            schema,\n            options,\n            z.object(\n              Object.fromEntries(\n                displayedAttrEntries.map(([attributeName, attribute]) => [\n                  attributeName,\n                  schemaZodParser(attribute, { ...options, defined: false })\n                ])\n              )\n            )\n          )\n        )"
)
with open(path, 'w') as f:
    f.write(content)
print("map parser done")
PYEOF
npx tsc --noEmit 2>&1 | head -40