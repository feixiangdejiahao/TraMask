cd /app && python3 - <<'PYEOF'
path = 'src/schema/actions/fromDTO/fromSchemaDTO/anyOf.ts'
with open(path) as f:
    content = f.read()

# add requiredIf to destructure
content = content.replace(
    "  const {\n    required,\n    hidden,\n    key,\n    savedAs,\n    discriminator,\n    keyDefault,\n    putDefault,\n    updateDefault,\n    keyLink,\n    putLink,\n    updateLink\n  } = props",
    "  const {\n    required,\n    requiredIf,\n    hidden,\n    key,\n    savedAs,\n    discriminator,\n    keyDefault,\n    putDefault,\n    updateDefault,\n    keyLink,\n    putLink,\n    updateLink\n  } = props"
)

# add requiredIf application after required block
content = content.replace(
    "  if (required !== undefined && required !== 'atLeastOnce') {\n    $attr = $attr.required(required)\n  }\n",
    "  if (required !== undefined && required !== 'atLeastOnce') {\n    $attr = $attr.required(required)\n  }\n\n  if (requiredIf !== undefined) {\n    for (const [attributeName, triggerValues] of Object.entries(requiredIf)) {\n      $attr = $attr.requiredIf(attributeName, ...triggerValues)\n    }\n  }\n"
)

with open(path, 'w') as f:
    f.write(content)
print("done")
PYEOF
cat src/schema/actions/fromDTO/fromSchemaDTO/anyOf.ts | sed -n '1,90p'