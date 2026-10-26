cd /app && cat > test_update_inspect.script.ts <<'EOF'
import { item, string, Table, Entity, UpdateItemCommand, $set, $get } from './src/index.js'

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
    console.log(label, JSON.stringify({ UpdateExpression: res.UpdateExpression, ConditionExpression: res.ConditionExpression, ToolboxItem: res.ToolboxItem }, (k,v)=>typeof v==='bigint'?v.toString():v, 2))
  } catch (e) {
    console.log(label, 'ERR', (e as any).message)
  }
}

show('set type a (plain)', { type: 'a' })
show('set type a via $set', { type: { [$set]: 'a' } })
show('set type a + details', { type: 'a', details: 'd' })
show('set type b', { type: 'b' })
EOF
cd /app && npx tsx test_update_inspect.script.ts