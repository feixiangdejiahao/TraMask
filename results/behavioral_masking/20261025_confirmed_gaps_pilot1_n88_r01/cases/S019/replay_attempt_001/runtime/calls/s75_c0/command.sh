cd /app && python3 - <<'PYEOF'
# item parser
path = 'src/schema/actions/parse/item.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import { schemaParser } from './schema.js'",
    "import { schemaParser } from './schema.js'\nimport { assertRequiredIf } from './utils.js'"
)
content = content.replace(
    "  const parsedValue = Object.fromEntries(\n    Object.entries(parsers)\n      .map(([attrName, attr]) => [attrName, attr.next().value])\n      .filter(([, attrValue]) => attrValue !== undefined)\n  )\n\n  if (transform) {",
    "  const parsedValue = Object.fromEntries(\n    Object.entries(parsers)\n      .map(([attrName, attr]) => [attrName, attr.next().value])\n      .filter(([, attrValue]) => attrValue !== undefined)\n  )\n\n  assertRequiredIf(schema, parsedValue, options)\n\n  if (transform) {"
)
with open(path, 'w') as f:
    f.write(content)
print("item updated")

# map parser
path = 'src/schema/actions/parse/map.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import { applyCustomValidation } from './utils.js'",
    "import { applyCustomValidation, assertRequiredIf } from './utils.js'"
)
content = content.replace(
    "  const parsedValue = Object.fromEntries(\n    Object.entries(parsers)\n      .map(([attrName, schemaParser]) => [attrName, schemaParser.next().value])\n      .filter(([, attrValue]) => attrValue !== undefined)\n  )\n  if (parsedValue !== undefined) {\n    applyCustomValidation(schema, parsedValue, options)\n  }",
    "  const parsedValue = Object.fromEntries(\n    Object.entries(parsers)\n      .map(([attrName, schemaParser]) => [attrName, schemaParser.next().value])\n      .filter(([, attrValue]) => attrValue !== undefined)\n  )\n  if (parsedValue !== undefined) {\n    applyCustomValidation(schema, parsedValue, options)\n  }\n\n  assertRequiredIf(schema, parsedValue, options)"
)
with open(path, 'w') as f:
    f.write(content)
print("map updated")
PYEOF
grep -n "assertRequiredIf" src/schema/actions/parse/item.ts src/schema/actions/parse/map.ts