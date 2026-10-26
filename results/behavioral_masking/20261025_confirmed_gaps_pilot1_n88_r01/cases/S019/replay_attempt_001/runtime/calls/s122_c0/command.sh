cd /app && python3 - <<'PYEOF'
# Formatter utils
path = 'src/schema/actions/zodSchemer/formatter/utils.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import { z } from 'zod'\n",
    "import { z } from 'zod'\n"
)
# add isObject import
content = content.replace(
    "import type { SavedAsAttributes } from '../utils.js'",
    "import type { SavedAsAttributes } from '../utils.js'\nimport { isObject } from '~/utils/validation/isObject.js'"
)
# append helper at end
content += '''

export const withRequiredIf = (
  schema: MapSchema | ItemSchema,
  zodSchema: z.ZodTypeAny
): z.ZodTypeAny =>
  zodSchema.superRefine((value, ctx) => {
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
'''
with open(path, 'w') as f:
    f.write(content)
print("formatter utils done")

# Parser utils
path = 'src/schema/actions/zodSchemer/parser/utils.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "import { z } from 'zod'\n",
    "import { z } from 'zod'\n"
)
content = content.replace(
    "import type { SavedAsAttributes } from '../utils.js'",
    "import type { SavedAsAttributes } from '../utils.js'\nimport { isObject } from '~/utils/validation/isObject.js'"
)
content += '''

export const withRequiredIf = (
  schema: MapSchema | ItemSchema,
  { mode }: ZodParserOptions,
  zodSchema: z.ZodTypeAny
): z.ZodTypeAny =>
  mode === 'put'
    ? zodSchema.superRefine((value, ctx) => {
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
    : zodSchema
'''
with open(path, 'w') as f:
    f.write(content)
print("parser utils done")
PYEOF