cd /app && cat > .tmp-savedas.ts <<'EOF'
import { item, string, Table, Entity, PutItemCommand, UpdateItemCommand } from './src/index.js'
const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })
const sch = item({
  pk: string().key(),
  type: string().savedAs('t').enum('a','b'),
  details: string().optional().savedAs('d').requiredIf('type','a')
})
sch.check()
const Ent = new Entity({ name: 'E', schema: sch, table, timestamps: false })
try {
  Ent.build(PutItemCommand).item({ pk: 'x', type: 'a' }).params()
} catch (e) {
  console.log('put err:', (e as any).code)
}
const r = Ent.build(UpdateItemCommand).item({ pk: 'x', type: 'a' }).params()
console.log('update cond:', r.ConditionExpression, JSON.stringify(r.ExpressionAttributeNames))
EOF
cd /app && npx tsx .tmp-savedas.ts && rm -f .tmp-savedas.ts