cd /app && python3 - <<'PYEOF'
path = 'src/schema/actions/zodSchemer/parser/utils.ts'
with open(path) as f:
    content = f.read()

idx = content.find('export const withRequiredIf')
content = content[:idx] + '''export const withRequiredIf = (
  schema: MapSchema | ItemSchema,
  { mode }: ZodParserOptions,
  zodSchema: z.ZodTypeAny
): z.ZodTypeAny => {
  const hasRequiredIf = Object.values(schema.attributes).some(attribute =>
    attribute.props.requiredIf !== undefined
  )

  if (!hasRequiredIf || mode !== 'put') {
    return zodSchema
  }

  return zodSchema.superRefine((value, ctx) => {
    if (!isObject(value)) {
      return
    }

    const recordValue = value as Record<string, unknown>

    for (const [attributeName, attribute] of Object.entries(schema.attributes)) {
      const { requiredIf } = attribute.props
      if (requiredIf === undefined) {
        continue
      }

      for (const [controllingAttributeName, triggerValues] of Object.entries(requiredIf)) {
        const controllingValue = recordValue[controllingAttributeName]
        if (controllingValue === undefined || !triggerValues.includes(controllingValue)) {
          continue
        }

        if (recordValue[attributeName] !== undefined) {
          continue
        }

        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `Attribute '${attributeName}' is required when '${controllingAttributeName}' is set to '${String(
            controllingValue
          )}'.`,
          path: [attributeName]
        })
      }
    }
  })
}
'''
with open(path, 'w') as f:
    f.write(content)
print('done')
PYEOF
npx tsc --noEmit 2>&1 | head -20