cd /app && cat > .tmp-test.ts <<'EOF'
import { item, string, Table, Entity, UpdateItemCommand, PutItemCommand, $set } from './src/index.js'

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
      UpdateExpression: res.UpdateExpression,
      ConditionExpression: res.ConditionExpression,
      ExpressionAttributeNames: res.ExpressionAttributeNames,
      ToolboxItem: res.ToolboxItem
    }, (k,v)=>typeof v==='bigint'?v.toString():v))
  } catch (e) {
    console.log(label, 'ERR', (e as any).message)
  }
}

show('set type a (plain) missing details', { type: 'a' })
show('set type a + details', { type: 'a', details: 'd' })
show('set type b', { type: 'b' })
show('set type a + remove details', { type: 'a', details: { [$set]: undefined } })

// nested map
const sch2 = item({
  pk: string().key(),
  profile: map({ type: string().enum('x','y'), bio: string().optional().requiredIf('type','x') }).savedAs('p')
})
sch2.check()
const Ent2 = new Entity({ name: 'E2', schema: sch2, table, timestamps: false })
const res2 = Ent2.build(UpdateItemCommand).item({ pk: 'x', profile: { type: 'x' } }).params()
console.log('nested', JSON.stringify({ ConditionExpression: res2.ConditionExpression, ExpressionAttributeNames: res2.ExpressionAttributeNames, UpdateExpression: res2.UpdateExpression }, (k,v)=>typeof v==='bigint'?v.toString():v))
EOF
cd /app && npx tsx .tmp-test.ts