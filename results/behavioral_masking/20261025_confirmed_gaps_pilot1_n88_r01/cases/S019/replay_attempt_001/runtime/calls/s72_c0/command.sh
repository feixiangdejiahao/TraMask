cd /app && cat > src/schema/actions/parse/errors.ts <<'EOF'
import type { ErrorBlueprint } from '~/errors/blueprint.js'

type InvalidItemErrorBlueprint = ErrorBlueprint<{
  code: 'parsing.invalidItem'
  hasPath: false
  payload: {
    received: unknown
    expected?: unknown
  }
}>

type AttributeRequiredErrorBlueprint = ErrorBlueprint<{
  code: 'parsing.attributeRequired'
  hasPath: true
  payload: undefined
}>

type ConditionalAttributeRequiredErrorBlueprint = ErrorBlueprint<{
  code: 'parsing.conditionalAttributeRequired'
  hasPath: true
  payload: {
    attributeName: string
    controllingAttributeName: string
    triggerValues: unknown[]
  }
}>

type InvalidAttributeInputErrorBlueprint = ErrorBlueprint<{
  code: 'parsing.invalidAttributeInput'
  hasPath: true
  payload: {
    received: unknown
    expected?: unknown
  }
}>

type CustomValidationFAiledErrorBlueprint = ErrorBlueprint<{
  code: 'parsing.customValidationFailed'
  hasPath: true
  payload: {
    received: unknown
    validationResult: unknown
  }
}>

export type ParserErrorBlueprints =
  | InvalidItemErrorBlueprint
  | AttributeRequiredErrorBlueprint
  | ConditionalAttributeRequiredErrorBlueprint
  | InvalidAttributeInputErrorBlueprint
  | CustomValidationFAiledErrorBlueprint
EOF
echo done