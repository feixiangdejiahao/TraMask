cd /app && cat > src/schema/types/schemaProps.ts <<'EOF'
import type { ComputeObject } from '~/types/computeObject.js'
import type { Overwrite } from '~/types/overwrite.js'

import type { Validator } from './validator.js'

/**
 * Tag for optional values
 */
export type Never = 'never'

/**
 * Tag for required at least once values
 */
export type AtLeastOnce = 'atLeastOnce'

/**
 * Tag for always required values
 */
export type Always = 'always'

/**
 * Available values for schema `required` properties
 */
export type SchemaRequiredProp = Never | AtLeastOnce | Always

/**
 * Conditional requirement: maps a sibling attribute name to the values
 * that make the current attribute required.
 */
export type RequiredIfValue = Record<string, unknown[]>

export interface SchemaProps {
  required?: SchemaRequiredProp
  requiredIf?: RequiredIfValue
  hidden?: boolean
  key?: boolean
  savedAs?: string
  keyDefault?: unknown
  putDefault?: unknown
  updateDefault?: unknown
  keyLink?: unknown
  putLink?: unknown
  updateLink?: unknown
  keyValidator?: Validator
  putValidator?: Validator
  updateValidator?: Validator
}

type MergeRequiredIfValues<
  REQUIRED_IF extends RequiredIfValue,
  NAME extends string,
  VALUES extends unknown[]
> = ComputeObject<{
  [KEY in keyof REQUIRED_IF | NAME]: KEY extends NAME
    ? NAME extends keyof REQUIRED_IF
      ? [...REQUIRED_IF[NAME], ...VALUES]
      : VALUES
    : KEY extends keyof REQUIRED_IF
      ? REQUIRED_IF[KEY]
      : never
}>

/**
 * Merge a new `requiredIf` declaration into existing schema props.
 * Calling `.requiredIf` several times accumulates trigger values (OR semantics).
 */
export type WithRequiredIf<
  PROPS extends SchemaProps,
  NAME extends string,
  VALUES extends unknown[]
> = PROPS extends { requiredIf: infer REQUIRED_IF }
  ? REQUIRED_IF extends RequiredIfValue
    ? Overwrite<PROPS, { requiredIf: MergeRequiredIfValues<REQUIRED_IF, NAME, VALUES> }>
    : Overwrite<PROPS, { requiredIf: { [KEY in NAME]: VALUES } }>
  : Overwrite<PROPS, { requiredIf: { [KEY in NAME]: VALUES } }>

export const mergeRequiredIf = (
  requiredIf: RequiredIfValue | undefined,
  attributeName: string,
  triggerValues: unknown[]
): RequiredIfValue => ({
  ...requiredIf,
  [attributeName]: [
    ...(requiredIf?.[attributeName] ?? []),
    ...triggerValues
  ]
})
EOF
echo "written"