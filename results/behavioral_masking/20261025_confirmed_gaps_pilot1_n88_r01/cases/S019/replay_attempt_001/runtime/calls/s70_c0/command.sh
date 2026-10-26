cd /app && cat > src/schema/utils/checkRequiredIf.ts <<'EOF'
import { DynamoDBToolboxError } from '~/errors/index.js'

import type { ItemSchema, MapSchema } from '../types/index.js'

/**
 * Validates `requiredIf` props on a map/item schema's attributes.
 *
 * @param schema Map or Item schema
 * @param path Path of the schema in the related schema (string)
 */
export const checkRequiredIf = (
  schema: MapSchema | ItemSchema,
  path?: string
): void => {
  for (const [attributeName, attribute] of Object.entries(schema.attributes)) {
    const { requiredIf, key } = attribute.props

    if (requiredIf === undefined) {
      continue
    }

    if (key) {
      throw new DynamoDBToolboxError('schema.invalidRequiredIf', {
        message: `Invalid requiredIf${
          path !== undefined ? ` at path '${path}.${attributeName}'` : ''
        }: Conditional requirements cannot be applied to key attributes.`,
        path,
        payload: { attributeName, reason: 'keyAttribute' }
      })
    }

    for (const [controllingAttributeName] of Object.entries(requiredIf)) {
      if (controllingAttributeName === attributeName) {
        throw new DynamoDBToolboxError('schema.invalidRequiredIf', {
          message: `Invalid requiredIf${
            path !== undefined ? ` at path '${path}.${attributeName}'` : ''
          }: An attribute cannot be required based on itself.`,
          path,
          payload: { attributeName, reason: 'selfReference' }
        })
      }

      if (!(controllingAttributeName in schema.attributes)) {
        throw new DynamoDBToolboxError('schema.invalidRequiredIf', {
          message: `Invalid requiredIf${
            path !== undefined ? ` at path '${path}.${attributeName}'` : ''
          }: Controlling attribute '${controllingAttributeName}' is not a sibling of '${attributeName}'.`,
          path,
          payload: { attributeName, reason: 'unknownAttribute' }
        })
      }
    }
  }
}
EOF
echo done