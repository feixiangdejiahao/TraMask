cd /app && cat > test_check.script.ts <<'EOF'
import { item, string, DynamoDBToolboxError } from './src/index.js'

function expectCheckError(label: string, fn: () => void) {
  try {
    fn()
    console.log(label, 'NO ERROR (bad)')
  } catch (e) {
    console.log(label, 'error:', e instanceof DynamoDBToolboxError ? e.code : e.constructor.name, (e as any).message)
  }
}

expectCheckError('key dependent', () =>
  item({ pk: string().key(), type: string(), details: string().key().requiredIf('type', 'a') }).check()
)
expectCheckError('key dependent 2', () =>
  item({ pk: string().key(), type: string(), details: string().required('always').requiredIf('type', 'a') }).check()
)
EOF
cd /app && npx tsx test_check.script.ts