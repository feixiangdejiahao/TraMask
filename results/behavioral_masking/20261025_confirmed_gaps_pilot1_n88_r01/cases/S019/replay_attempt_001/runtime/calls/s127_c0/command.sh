cd /app && python3 - <<'PYEOF'
# Formatter utils
path = 'src/schema/actions/zodSchemer/formatter/utils.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "export const withRequiredIf = (\n  schema: MapSchema | ItemSchema,\n  zodSchema: z.ZodTypeAny\n): z.ZodTypeAny =>\n  zodSchema.superRefine((value, ctx) => {",
    "export const withRequiredIf = (\n  schema: MapSchema | ItemSchema,\n  zodSchema: z.ZodTypeAny\n): z.ZodTypeAny => {\n  const hasRequiredIf = Object.values(schema.attributes).some(attribute =>\n    attribute.props.requiredIf !== undefined\n  )\n\n  if (!hasRequiredIf) {\n    return zodSchema\n  }\n\n  return zodSchema.superRefine((value, ctx) => {"
)
# close the function: the helper currently ends with "  })\n"
# We need to add closing brace. Replace last "  })\n" near end with "  })\n}\n"
# Find the unique ending
content = content.rstrip()
if content.endswith('  })'):
    content += '\n}\n'
else:
    content += '\n}\n'
with open(path, 'w') as f:
    f.write(content)
print("formatter helper patched")

# Parser utils
path = 'src/schema/actions/zodSchemer/parser/utils.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "export const withRequiredIf = (\n  schema: MapSchema | ItemSchema,\n  { mode }: ZodParserOptions,\n  zodSchema: z.ZodTypeAny\n): z.ZodTypeAny =>\n  mode === 'put'\n    ? zodSchema.superRefine((value, ctx) => {",
    "export const withRequiredIf = (\n  schema: MapSchema | ItemSchema,\n  { mode }: ZodParserOptions,\n  zodSchema: z.ZodTypeAny\n): z.ZodTypeAny => {\n  const hasRequiredIf = Object.values(schema.attributes).some(attribute =>\n    attribute.props.requiredIf !== undefined\n  )\n\n  if (!hasRequiredIf) {\n    return zodSchema\n  }\n\n  if (mode !== 'put') {\n    return zodSchema\n  }\n\n  return zodSchema.superRefine((value, ctx) => {"
)
content = content.rstrip()
if content.endswith('  })'):
    content += '\n}\n'
elif content.endswith('    : zodSchema'):
    content += '\n}\n'
else:
    content += '\n}\n'
with open(path, 'w') as f:
    f.write(content)
print("parser helper patched")
PYEOF
sed -n '90,150p' src/schema/actions/zodSchemer/formatter/utils.ts