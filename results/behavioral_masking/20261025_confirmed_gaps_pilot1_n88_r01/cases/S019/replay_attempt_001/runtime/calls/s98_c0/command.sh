cd /app && cat > test_default.script.ts <<'EOF'
import { item, string, Table, Entity, PutItemCommand } from './src/index.js'

const sch = item({
  pk: string().key(),
  type: string().enum('a', 'b'),
  details: string().optional().putDefault('default-details').requiredIf('type', 'a')
})
sch.check()
const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })
const Ent = new Entity({ name: 'E', schema: sch, table, timestamps: false })
const res = Ent.build(PutItemCommand).item({ pk: 'x', type: 'a' }).params()
console.log('item:', JSON.stringify(res.Item))
EOF
cd /app && npx tsx test_default.script.ts