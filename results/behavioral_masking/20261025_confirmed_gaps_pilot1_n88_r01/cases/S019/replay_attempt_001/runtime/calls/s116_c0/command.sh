cd /app && cat > src/schema/actions/jsonSchemer/formattedValue/shared.ts <<'EOF'
import type { ItemSchema, MapSchema, Never, RequiredIfValue } from '~/schema/index.js'
import type { OmitKeys } from '~/types/omitKeys.js'

export type RequiredProperties<SCHEMA extends MapSchema | ItemSchema> = ItemSchema extends SCHEMA
  ? string
  : MapSchema extends SCHEMA
    ? string
    : {
        [KEY in OmitKeys<
          SCHEMA['attributes'],
          { props: { hidden: true } }
        >]: SCHEMA['attributes'][KEY]['props'] extends { required: Never } ? never : KEY
      }[OmitKeys<SCHEMA['attributes'], { props: { hidden: true } }>]

export interface RequiredIfJSONSchema {
  if: {
    properties: Record<string, { enum: unknown[] }>
    required: [string]
  }
  then: {
    required: string[]
  }
}

export type RequiredIfJSONSchemas =
  | RequiredIfJSONSchema
  | { allOf: RequiredIfJSONSchema[] }

export const getRequiredIfJSONSchema = (
  schema: MapSchema | ItemSchema
): RequiredIfJSONSchemas | undefined => {
  const requiredIfEntries: RequiredIfJSONSchema[] = []

  for (const [attributeName, attribute] of Object.entries(schema.attributes)) {
    const { requiredIf } = attribute.props
    if (requiredIf === undefined) {
      continue
    }

    for (const [controllingAttributeName, triggerValues] of Object.entries(
      requiredIf as RequiredIfValue
    )) {
      requiredIfEntries.push({
        if: {
          properties: {
            [controllingAttributeName]: { enum: triggerValues }
          },
          required: [controllingAttributeName]
        },
        then: {
          required: [attributeName]
        }
      })
    }
  }

  if (requiredIfEntries.length === 0) {
    return undefined
  }

  if (requiredIfEntries.length === 1) {
    return requiredIfEntries[0]
  }

  return { allOf: requiredIfEntries }
}
EOF
echo done