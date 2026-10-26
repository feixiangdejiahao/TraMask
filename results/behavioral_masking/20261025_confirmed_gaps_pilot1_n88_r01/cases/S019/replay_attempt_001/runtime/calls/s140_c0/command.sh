cd /app && cat > .tmp-anyofattr.ts <<'EOF'
import { item, anyOf, string, number, Table, Entity, PutItemCommand } from './src/index.js'
const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })
const sch = item({
  pk: string().key(),
  type: string().enum('a','b'),
  value: anyOf(string(), number()).optional().requiredIf('type', 'a')
})
sch.check()
const Ent = new Entity({ name: 'E', schema: sch, table, timestamps: false })
try {
  Ent.build(PutItemCommand).item({ pk: 'x', type: 'a' }).params()
  console.log('NO ERROR (bad)')
} catch (e) {
  console.log('err:', (e as any).code)
}
try {
  Ent.build(PutItemCommand).item({ pk: 'x', type: 'a', value: 'v' }).params()
  console.log('OK')
} catch (e) {
  console.log('ERR', (e as any).message)
}
EOF
cd /app && npx tsx .tmp-anyofattr.ts