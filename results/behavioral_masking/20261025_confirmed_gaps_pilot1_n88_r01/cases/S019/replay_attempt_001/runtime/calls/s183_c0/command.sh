cd /app && cat > .tmp-final.ts <<'EOF'
import { item, map, anyOf, string, Table, Entity, UpdateItemCommand, PutItemCommand } from './src/index.js'

const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })

// 1. combine with user condition
const sch1 = item({ pk: string().key(), type: string().enum('a','b'), details: string().optional().requiredIf('type','a') })
sch1.check()
const Ent1 = new Entity({ name: 'E', schema: sch1, table, timestamps: false })
const r1 = Ent1.build(UpdateItemCommand).item({ pk: 'x', type: 'a' }).options({ condition: { attr: 'pk', eq: 'x' } }).params()
console.log('combined:', r1.ConditionExpression, JSON.stringify(r1.ExpressionAttributeNames))

// 2. nested anyOf update
const sch2 = item({
  pk: string().key(),
  data: anyOf(
    map({ kind: string().enum('x','y'), bio: string().optional().requiredIf('kind','x') })
  )
})
sch2.check()
const Ent2 = new Entity({ name: 'E2', schema: sch2, table, timestamps: false })
const r2 = Ent2.build(UpdateItemCommand).item({ pk: 'x', data: { kind: 'x' } }).params()
console.log('anyOf update:', r2.ConditionExpression, JSON.stringify(r2.ExpressionAttributeNames))

// 3. absent controlling attribute in put
const r3 = Ent1.build(PutItemCommand).item({ pk: 'x', details: 'd' }).params()
console.log('put absent control ok, item:', JSON.stringify(r3.Item))
EOF
cd /app && npx tsx .tmp-final.ts