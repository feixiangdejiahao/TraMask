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

export type RequiredIfJSONSchemas = RequiredIfJSONSchema | { allOf: RequiredIfJSONSchema[] }

export const getRequiredIfJSONSchema = (
  schema: MapSchema | ItemSchema
): RequiredIfJSONSchemas | undefined => {
  const merged: Record<string, Record<string, unknown[]>> = {}

  for (const [attributeName, attribute] of Object.entries(schema.attributes)) {
    const { requiredIf } = attribute.props
    if (requiredIf === undefined) {
      continue
    }

    for (const [controllingAttributeName, triggerValues] of Object.entries(
      requiredIf as RequiredIfValue
    )) {
      merged[attributeName] ??= {}
      merged[attributeName][controllingAttributeName] ??= []
      merged[attributeName][controllingAttributeName].push(...triggerValues)
    }
  }

  const requiredIfEntries: RequiredIfJSONSchema[] = []

  for (const [attributeName, rules] of Object.entries(merged)) {
    for (const [controllingAttributeName, triggerValues] of Object.entries(rules)) {
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
npx prettier --write src/schema/actions/jsonSchemer/formattedValue/shared.ts >/dev/null && npx tsc --noEmit 2>&1 | head -5 && npx vitest run src/schema/actions/jsonSchemer --reporter=dot 2>&1 | tail -6