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

expectCheckError('unknown control', () =>
  item({ type: string(), details: string().optional().requiredIf('foo', 'a') }).check()
)
expectCheckError('self ref', () =>
  item({ details: string().optional().requiredIf('details', 'a') }).check()
)
expectCheckError('key dependent', () =>
  item({ pk: string().key(), details: string().optional().requiredIf('pk', 'a') }).check()
)
// key controlling should be allowed? check
expectCheckError('key controlling', () =>
  item({ pk: string().key(), type: string(), details: string().optional().requiredIf('pk', 'a') }).check()
)
EOF
cd /app && npx tsx test_check.script.ts