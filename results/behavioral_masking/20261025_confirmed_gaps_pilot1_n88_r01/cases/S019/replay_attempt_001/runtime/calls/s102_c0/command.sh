cd /app && cat > src/entity/actions/update/updateItemParams/requiredIfConditions.ts <<'EOF'
import { Finder } from '~/schema/actions/finder/index.js'
import { formatArrayPath } from '~/schema/actions/utils/formatArrayPath.js'
import type { ArrayPath } from '~/schema/actions/utils/types.js'
import type { ItemSchema, MapSchema, Schema } from '~/schema/index.js'
import { isObject } from '~/utils/validation/isObject.js'

import { isRemoval, isSetting } from '../symbols/index.js'
import type { UpdateItemInputExtension } from '../types.js'

interface RequiredIfConditionState {
  rootSchema: Schema
  conditions: string[]
  ExpressionAttributeNames: Record<string, string>
  tokens: Record<string, string>
  nameCursor: number
}

export interface RequiredIfCondition {
  ConditionExpression: string
  ExpressionAttributeNames: Record<string, string>
}

const pathTokens = (path: ArrayPath, state: RequiredIfConditionState): string => {
  let tokens = ''

  path.forEach((pathPart, index) => {
    if (typeof pathPart === 'number') {
      tokens += `[${pathPart}]`
      return
    }

    let token = state.tokens[pathPart]
    if (token === undefined) {
      token = `#c_${state.nameCursor}`
      state.tokens[pathPart] = token
      state.ExpressionAttributeNames[token] = pathPart
      state.nameCursor++
    }

    if (index > 0) {
      tokens += '.'
    }

    tokens += token
  })

  return tokens
}

/**
 * Collects `attribute_exists` conditions for `requiredIf` rules that would be
 * violated by an UPDATE that sets a controlling attribute to a trigger value
 * while leaving a dependent attribute absent.
 */
export const getRequiredIfConditions = (
  entitySchema: ItemSchema,
  input: UpdateItemInputExtension | Record<string, unknown>
): RequiredIfCondition | undefined => {
  const state: RequiredIfConditionState = {
    rootSchema: entitySchema,
    conditions: [],
    ExpressionAttributeNames: {},
    tokens: {},
    nameCursor: 1
  }

  collectRequiredIfConditions(entitySchema, input, [], state)

  if (state.conditions.length === 0) {
    return undefined
  }

  return {
    ConditionExpression: state.conditions.join(' AND '),
    ExpressionAttributeNames: state.ExpressionAttributeNames
  }
}

const collectRequiredIfConditions = (
  schema: Schema,
  value: unknown,
  path: ArrayPath,
  state: RequiredIfConditionState
): void => {
  if (value === undefined || value === null) {
    return
  }

  const unwrappedValue = isSetting(value) ? (value as { [$set]: unknown })[isSettingSymbol] : value
  if (!isObject(unwrappedValue)) {
    return
  }

  switch (schema.type) {
    case 'item':
    case 'map': {
      collectRequiredIfFromMapOrItem(schema, unwrappedValue, path, state)
      break
    }
    case 'anyOf': {
      for (const element of schema.elements) {
        collectRequiredIfConditions(element, unwrappedValue, path, state)
      }
      return
    }
    case 'list': {
      if (!Array.isArray(unwrappedValue)) {
        return
      }
      unwrappedValue.forEach((elementValue, index) => {
        collectRequiredIfConditions(schema.elements, elementValue, [...path, index], state)
      })
      return
    }
    case 'record': {
      for (const [key, elementValue] of Object.entries(unwrappedValue)) {
        collectRequiredIfConditions(schema.elements, elementValue, [...path, key], state)
      }
      return
    }
    default:
      return
  }

  // Recurse into children
  for (const [key, childValue] of Object.entries(unwrappedValue)) {
    const childSchema = getChildSchema(schema, key)
    if (childSchema !== undefined) {
      collectRequiredIfConditions(childSchema, childValue, [...path, key], state)
    }
  }
}

const collectRequiredIfFromMapOrItem = (
  schema: MapSchema | ItemSchema,
  value: Record<string, unknown>,
  path: ArrayPath,
  state: RequiredIfConditionState
): void => {
  for (const [attributeName, attribute] of Object.entries(schema.attributes)) {
    const { requiredIf } = attribute.props
    if (requiredIf === undefined) {
      continue
    }

    for (const [controllingAttributeName, triggerValues] of Object.entries(requiredIf)) {
      const controllingValue = getSetValue(value[controllingAttributeName])
      if (controllingValue === undefined || !triggerValues.includes(controllingValue)) {
        continue
      }

      const dependentValue = value[attributeName]
      if (dependentValue !== undefined && !isRemoval(dependentValue)) {
        continue
      }

      const fullPath = [...path, attributeName]
      const [subSchema] = new Finder(state.rootSchema).search(formatArrayPath(fullPath))
      if (subSchema === undefined) {
        continue
      }

      const transformedArrayPath = subSchema.transformedPath.arrayPath
      const tokens = pathTokens(transformedArrayPath, state)
      state.conditions.push(`attribute_exists(${tokens})`)
    }
  }
}

const getChildSchema = (schema: Schema, key: string | number): Schema | undefined => {
  switch (schema.type) {
    case 'item':
    case 'map':
      return schema.attributes[key as string]
    default:
      return undefined
  }
}

// Minimal helper to read the value of a `$set` wrapper without importing symbols
const isSettingSymbol = Symbol.for('$SET')
const getSetValue = (input: unknown): unknown => {
  if (isSetting(input)) {
    return (input as { [$set]: unknown })[isSettingSymbol]
  }
  return input
}
EOF
echo done