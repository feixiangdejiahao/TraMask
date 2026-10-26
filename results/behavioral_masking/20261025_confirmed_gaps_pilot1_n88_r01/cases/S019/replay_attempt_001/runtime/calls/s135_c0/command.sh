cd /app && cat > .tmp-edge.ts <<'EOF'
import { item, map, anyOf, string, number, Table, Entity, PutItemCommand, UpdateItemCommand, $set } from './src/index.js'

const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })

// anyOf of maps with requiredIf inside
const sch = item({
  pk: string().key(),
  data: anyOf(
    map({ kind: string().enum('x','y'), bio: string().optional().requiredIf('kind','x') }),
    map({ kind: string().enum('z'), extra: string() })
  )
})
sch.check()
const Ent = new Entity({ name: 'E', schema: sch, table, timestamps: false })

try {
  Ent.build(PutItemCommand).item({ pk: 'x', data: { kind: 'x' } }).params()
  console.log('put anyOf missing bio: NO ERROR (bad)')
} catch (e) {
  console.log('put anyOf missing bio err:', (e as any).code)
}
try {
  Ent.build(PutItemCommand).item({ pk: 'x', data: { kind: 'x', bio: 'b' } }).params()
  console.log('put anyOf with bio OK')
} catch (e) {
  console.log('put anyOf with bio ERR', (e as any).message)
}

// update nested $set map
const sch2 = item({
  pk: string().key(),
  profile: map({ type: string().enum('x','y'), bio: string().optional().requiredIf('type','x') })
})
sch2.check()
const Ent2 = new Entity({ name: 'E2', schema: sch2, table, timestamps: false })
const res = Ent2.build(UpdateItemCommand).item({ pk: 'x', profile: { [$set]: { type: 'x' } } }).params()
console.log('update $set map:', JSON.stringify({ ConditionExpression: res.ConditionExpression, EAN: res.ExpressionAttributeNames }, (k,v)=>typeof v==='bigint'?v.toString():v))

// multiple rules same dependent -> dedupe?
const sch3 = item({
  pk: string().key(),
  type: string().enum('a','b'),
  flag: string().optional(),
  details: string().optional().requiredIf('type','a').requiredIf('flag','on')
})
sch3.check()
const Ent3 = new Entity({ name: 'E3', schema: sch3, table, timestamps: false })
const res3 = Ent3.build(UpdateItemCommand).item({ pk: 'x', type: 'a', flag: 'on' }).params()
console.log('multi rules:', JSON.stringify({ ConditionExpression: res3.ConditionExpression }, (k,v)=>typeof v==='bigint'?v.toString():v))
EOF
cd /app && npx tsx .tmp-edge.ts