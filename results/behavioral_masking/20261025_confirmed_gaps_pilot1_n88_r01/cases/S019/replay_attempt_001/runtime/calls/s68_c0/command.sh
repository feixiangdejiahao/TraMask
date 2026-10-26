cd /app && cat > src/schema/utils/checkSchemaProps.ts <<'EOF'
import { DynamoDBToolboxError } from '~/errors/index.js'
import { isBoolean } from '~/utils/validation/isBoolean.js'
import { isObject } from '~/utils/validation/isObject.js'
import { isString } from '~/utils/validation/isString.js'

import type { SchemaProps, SchemaRequiredProp } from '../types/index.js'

export const schemaRequiredPropSet = new Set<SchemaRequiredProp>(['never', 'atLeastOnce', 'always'])

/**
 * Validates an attribute shared properties
 *
 * @param props Schema Props
 * @param path Path of the instance in the related schema (string)
 * @return void
 */
export const checkSchemaProps = (props: SchemaProps, path?: string): void => {
  const { required, requiredIf, hidden, key, savedAs } = props

  if (required !== undefined && !schemaRequiredPropSet.has(required)) {
    throw new DynamoDBToolboxError('schema.invalidProp', {
      message: `Invalid prop type${
        path !== undefined ? ` at path '${path}'` : ''
      }. Property: 'required'. Expected: ${[...schemaRequiredPropSet].join(', ')}. Received: ${String(
        required
      )}.`,
      path,
      payload: {
        propName: 'required',
        expected: [...schemaRequiredPropSet].join(', '),
        received: required
      }
    })
  }

  if (requiredIf !== undefined && (!isObject(requiredIf) || Array.isArray(requiredIf))) {
    throw new DynamoDBToolboxError('schema.invalidProp', {
      message: `Invalid prop type${
        path !== undefined ? ` at path '${path}'` : ''
      }. Property: 'requiredIf'. Expected: an object. Received: ${String(requiredIf)}.`,
      path,
      payload: {
        propName: 'requiredIf',
        expected: 'object',
        received: requiredIf
      }
    })
  }

  if (requiredIf !== undefined) {
    for (const [attributeName, triggerValues] of Object.entries(requiredIf)) {
      if (!isString(attributeName)) {
        throw new DynamoDBToolboxError('schema.invalidProp', {
          message: `Invalid prop type${
            path !== undefined ? ` at path '${path}'` : ''
          }. Property: 'requiredIf'. Expected attribute names to be strings.`,
          path,
          payload: {
            propName: 'requiredIf',
            expected: 'string',
            received: attributeName
          }
        })
      }

      if (!Array.isArray(triggerValues)) {
        throw new DynamoDBToolboxError('schema.invalidProp', {
          message: `Invalid prop type${
            path !== undefined ? ` at path '${path}'` : ''
          }. Property: 'requiredIf'. Expected trigger values for '${attributeName}' to be an array.`,
          path,
          payload: {
            propName: 'requiredIf',
            expected: 'array',
            received: triggerValues
          }
        })
      }
    }
  }

  if (hidden !== undefined && !isBoolean(hidden)) {
    throw new DynamoDBToolboxError('schema.invalidProp', {
      message: `Invalid prop type${
        path !== undefined ? ` at path '${path}'` : ''
      }. Property: 'hidden'. Expected: boolean. Received: ${String(hidden)}.`,
      path,
      payload: {
        propName: 'hidden',
        received: hidden
      }
    })
  }

  if (key !== undefined && !isBoolean(key)) {
    throw new DynamoDBToolboxError('schema.invalidProp', {
      message: `Invalid prop type${
        path !== undefined ? ` at path '${path}'` : ''
      }. Property: 'key'. Expected: boolean. Received: ${String(key)}.`,
      path,
      payload: {
        propName: 'key',
        received: key
      }
    })
  }

  if (savedAs !== undefined && !isString(savedAs)) {
    throw new DynamoDBToolboxError('schema.invalidProp', {
      message: `Invalid prop type${
        path !== undefined ? ` at path '${path}'` : ''
      }. Property: 'savedAs'. Expected: string. Received: ${String(savedAs)}.`,
      path,
      payload: {
        propName: 'savedAs',
        received: savedAs
      }
    })
  }
}
EOF
echo "done"