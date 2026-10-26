cd /app && cat > src/schema/utils/errors.ts <<'EOF'
import type { ErrorBlueprint } from '~/errors/blueprint.js'

type InvalidPropErrorBlueprint = ErrorBlueprint<{
  code: 'schema.invalidProp'
  hasPath: true
  payload: {
    propName: string
    expected?: unknown
    received: unknown
  }
}>

type InvalidRequiredIfErrorBlueprint = ErrorBlueprint<{
  code: 'schema.invalidRequiredIf'
  hasPath: true
  payload: {
    attributeName: string
    reason: 'unknownAttribute' | 'selfReference' | 'keyAttribute'
  }
}>

export type SharedSchemaErrorBlueprint = InvalidPropErrorBlueprint | InvalidRequiredIfErrorBlueprint
EOF
echo done