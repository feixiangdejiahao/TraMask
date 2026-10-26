cd /app && python3 - <<'PYEOF'
for path in ['src/schema/actions/jsonSchemer/formattedValue/item.ts', 'src/schema/actions/jsonSchemer/formattedValue/map.ts']:
    with open(path) as f:
        content = f.read()
    # Replace the weird type block
    content = content.replace(
        "  } & ([REQUIRED_PROPERTIES] extends [never] ? {} : { required: REQUIRED_PROPERTIES[] }) & {\n    if?: RequiredIfJSONSchemas extends infer R ? (R extends { allOf: unknown[] } ? never : R) : never\n    then?: RequiredIfJSONSchemas extends infer R ? (R extends { allOf: unknown[] } ? never : R) : never\n    allOf?: RequiredIfJSONSchemas extends { allOf: unknown[] } ? RequiredIfJSONSchemas : never  }\n>",
        "  } & ([REQUIRED_PROPERTIES] extends [never] ? {} : { required: REQUIRED_PROPERTIES[] }) & {\n    if?: RequiredIfJSONSchemas extends { if: infer IF } ? IF : never\n    then?: RequiredIfJSONSchemas extends { then: infer THEN } ? THEN : never\n    allOf?: RequiredIfJSONSchemas extends { allOf: infer ALL_OF } ? ALL_OF : never\n  }\n>"
    )
    with open(path, 'w') as f:
        f.write(content)
    print(path, 'patched')
PYEOF
npx tsc --noEmit 2>&1 | head -30