cd /app && python3 - <<'PYEOF'
for path in ['src/schema/actions/jsonSchemer/formattedValue/item.ts', 'src/schema/actions/jsonSchemer/formattedValue/map.ts']:
    with open(path) as f:
        content = f.read()

    # update import of shared
    content = content.replace(
        "import type { RequiredProperties } from './shared.js'",
        "import type { RequiredIfJSONSchemas, RequiredProperties } from './shared.js'\nimport { getRequiredIfJSONSchema } from './shared.js'"
    )

    # update type to include conditional
    content = content.replace(
        "  } & ([REQUIRED_PROPERTIES] extends [never] ? {} : { required: REQUIRED_PROPERTIES[] })\n>",
        "  } & ([REQUIRED_PROPERTIES] extends [never] ? {} : { required: REQUIRED_PROPERTIES[] }) & {\n    if?: RequiredIfJSONSchemas extends infer R ? (R extends { allOf: unknown[] } ? { allOf: RequiredIfJSONSchemas } : R) : never\n    then?: RequiredIfJSONSchemas extends { if: unknown } ? RequiredIfJSONSchemas : never\n    allOf?: RequiredIfJSONSchemas extends { allOf: unknown[] } ? RequiredIfJSONSchemas : never\n  }\n>"
    )
    # Actually simpler: replace with a version that adds optional allOf/if/then as unknown
    content = content.replace(
        "    if?: RequiredIfJSONSchemas extends infer R ? (R extends { allOf: unknown[] } ? { allOf: RequiredIfJSONSchemas } : R) : never\n    then?: RequiredIfJSONSchemas extends { if: unknown } ? RequiredIfJSONSchemas : never\n    allOf?: RequiredIfJSONSchemas extends { allOf: unknown[] } ? RequiredIfJSONSchemas : never\n",
        "    if?: RequiredIfJSONSchemas extends infer R ? (R extends { allOf: unknown[] } ? never : R) : never\n    then?: RequiredIfJSONSchemas extends infer R ? (R extends { allOf: unknown[] } ? never : R) : never\n    allOf?: RequiredIfJSONSchemas extends { allOf: unknown[] } ? RequiredIfJSONSchemas : never"
    )

    # add runtime conditional after required spread
    content = content.replace(
        "    ...(requiredProperties.length > 0 ? { required: requiredProperties } : {})\n  } as ",
        "    ...(requiredProperties.length > 0 ? { required: requiredProperties } : {}),\n    ...(getRequiredIfJSONSchema(schema) !== undefined\n      ? (getRequiredIfJSONSchema(schema) as object)\n      : {})\n  } as "
    )

    with open(path, 'w') as f:
        f.write(content)
    print(f"{path}: updated")
PYEOF
sed -n '1,80p' src/schema/actions/jsonSchemer/formattedValue/item.ts