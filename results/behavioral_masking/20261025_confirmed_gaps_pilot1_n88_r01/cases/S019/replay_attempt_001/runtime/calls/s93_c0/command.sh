cd /app && cat > /tmp/test_requiredif.ts <<'EOF'
import { item, map, string, number, DynamoDBToolboxError } from './src/index.js'

const sch = item({
  pk: string().key(),
  type: string().enum('a', 'b'),
  details: string().optional().requiredIf('type', 'a')
})

// check should pass
try {
  sch.check()
  console.log('check OK')
} catch (e) {
  console.log('check FAILED', e)
}

// put with type a but no details -> error
const Entity = new (await import('./src/index.js')).Entity({
  name: 'Test',
  schema: sch,
  table: new (await import('./src/index.js')).Table({
    name: 'test',
    partitionKey: { type: 'string', name: 'pk' }
  }),
  timestamps: false
})

try {
  Entity.build((await import('./src/index.js')).PutItemCommand).item({ pk: 'x', type: 'a' }).params()
  console.log('put with missing dependent: NO ERROR (bad)')
} catch (e) {
  console.log('put error:', e instanceof DynamoDBToolboxError ? e.code : e.constructor.name, (e as any).message)
}

// put with type b without details -> ok
try {
  const res = Entity.build((await import('./src/index.js')).PutItemCommand).item({ pk: 'x', type: 'b' }).params()
  console.log('put type b ok, item:', JSON.stringify(res.Item))
} catch (e) {
  console.log('put type b FAILED', e)
}

// put with type a and details -> ok
try {
  const res = Entity.build((await import('./src/index.js')).PutItemCommand).item({ pk: 'x', type: 'a', details: 'd' }).params()
  console.log('put type a with details ok')
} catch (e) {
  console.log('put type a with details FAILED', e)
}
EOF
cd /app && npx tsx /tmp/test_requiredif.ts