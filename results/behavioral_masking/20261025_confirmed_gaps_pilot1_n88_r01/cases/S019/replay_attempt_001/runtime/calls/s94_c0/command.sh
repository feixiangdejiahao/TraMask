cd /app && cat > /tmp/test_requiredif.ts <<'EOF'
import {
  item, string, Table, Entity, PutItemCommand, DynamoDBToolboxError
} from './src/index.js'

const sch = item({
  pk: string().key(),
  type: string().enum('a', 'b'),
  details: string().optional().requiredIf('type', 'a')
})

try {
  sch.check()
  console.log('check OK')
} catch (e) {
  console.log('check FAILED', e)
}

const table = new Table({
  name: 'test',
  partitionKey: { type: 'string', name: 'pk' }
})

const Entity1 = new Entity({
  name: 'Test',
  schema: sch,
  table,
  timestamps: false
})

try {
  Entity1.build(PutItemCommand).item({ pk: 'x', type: 'a' }).params()
  console.log('put with missing dependent: NO ERROR (bad)')
} catch (e) {
  console.log('put error:', e instanceof DynamoDBToolboxError ? e.code : e.constructor.name, (e as any).message)
}

try {
  const res = Entity1.build(PutItemCommand).item({ pk: 'x', type: 'b' }).params()
  console.log('put type b ok, item:', JSON.stringify(res.Item))
} catch (e) {
  console.log('put type b FAILED', e)
}

try {
  Entity1.build(PutItemCommand).item({ pk: 'x', type: 'a', details: 'd' }).params()
  console.log('put type a with details ok')
} catch (e) {
  console.log('put type a with details FAILED', e)
}
EOF
cd /app && npx tsx /tmp/test_requiredif.ts