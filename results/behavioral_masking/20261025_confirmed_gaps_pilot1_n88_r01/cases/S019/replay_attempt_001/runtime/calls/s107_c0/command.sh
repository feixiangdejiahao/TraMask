cd /app && cat > .tmp-test.ts <<'EOF'
import { item, string, map, Table, Entity, UpdateItemCommand } from './src/index.js'

const sch = item({
  pk: string().key(),
  type: string().enum('a', 'b'),
  details: string().optional().requiredIf('type', 'a')
})
sch.check()
const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })
const Ent = new Entity({ name: 'E', schema: sch, table, timestamps: false })

function show(label: string, input: any) {
  try {
    const res = Ent.build(UpdateItemCommand).item({ pk: 'x', ...input }).params()
    console.log(label, JSON.stringify({
      ConditionExpression: res.ConditionExpression,
      ExpressionAttributeNames: res.ExpressionAttributeNames
    }, (k,v)=>typeof v==='bigint'?v.toString():v))
  } catch (e) {
    console.log(label, 'ERR', (e as any).message)
  }
}

show('top missing', { type: 'a' })
show('top present', { type: 'a', details: 'd' })
show('top b', { type: 'b' })

// nested map with savedAs
const sch2 = item({
  pk: string().key(),
  profile: map({ type: string().enum('x','y'), bio: string().optional().requiredIf('type','x') }).savedAs('p')
})
sch2.check()
const Ent2 = new Entity({ name: 'E2', schema: sch2, table, timestamps: false })
const res2 = Ent2.build(UpdateItemCommand).item({ pk: 'x', profile: { type: 'x' } }).params()
console.log('nested', JSON.stringify({ ConditionExpression: res2.ConditionExpression, ExpressionAttributeNames: res2.ExpressionAttributeNames }, (k,v)=>typeof v==='bigint'?v.toString():v))

// nested with savedAs inside dependent
const sch3 = item({
  pk: string().key(),
  profile: map({ type: string().enum('x','y'), bio: string().optional().savedAs('b').requiredIf('type','x') }).savedAs('p')
})
sch3.check()
const Ent3 = new Entity({ name: 'E3', schema: sch3, table, timestamps: false })
const res3 = Ent3.build(UpdateItemCommand).item({ pk: 'x', profile: { type: 'x' } }).params()
console.log('nested savedAs dep', JSON.stringify({ ConditionExpression: res3.ConditionExpression, ExpressionAttributeNames: res3.ExpressionAttributeNames }, (k,v)=>typeof v==='bigint'?v.toString():v))
EOF
cd /app && npx tsx .tmp-test.ts