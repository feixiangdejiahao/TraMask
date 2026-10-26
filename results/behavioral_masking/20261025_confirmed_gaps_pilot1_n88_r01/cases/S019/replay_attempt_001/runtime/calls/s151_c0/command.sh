cd /app && python3 - <<'PYEOF'
path = 'src/schema/actions/zodSchemer/formatter/map.ts'
with open(path) as f:
    content = f.read()

old = """      withValidate(
        schema,
        z.object(
          Object.fromEntries(
            displayedAttrEntries.map(([attributeName, attribute]) => [
              attributeName,
              schemaZodFormatter(attribute, { ...options, defined: false })
            ])
          )
        )
      )"""
new = """      withValidate(
        schema,
        withRequiredIf(
          schema,
          z.object(
            Object.fromEntries(
              displayedAttrEntries.map(([attributeName, attribute]) => [
                attributeName,
                schemaZodFormatter(attribute, { ...options, defined: false })
              ])
            )
          )
        )
      )"""
assert old in content, "pattern not found"
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('map formatter patched')
PYEOF
npx prettier --write src/schema/actions/zodSchemer/formatter/map.ts && npx eslint src/schema/actions/zodSchemer/formatter/map.ts 2>&1 | head