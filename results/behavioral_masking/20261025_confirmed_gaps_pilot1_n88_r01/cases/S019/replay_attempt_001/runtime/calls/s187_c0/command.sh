cd /app && cat > .tmp-mapattr.ts <<'EOF'
import { item, map, string, Table, Entity, UpdateItemCommand } from './src/index.js'
const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })
const sch = item({
  pk: string().key(),
  type: string().enum('x','y'),
  profile: map({ a: string() }).optional().savedAs('p').requiredIf('type','x')
})
sch.check()
const Ent = new Entity({ name: 'E', schema: sch, table, timestamps: false })
const res = Ent.build(UpdateItemCommand).item({ pk: 'x', type: 'x' }).params()
console.log(res.ConditionExpression, JSON.stringify(res.ExpressionAttributeNames))
EOF
cd /app && npx tsx .tmp-mapattr.ts && rm -f .tmp-mapattr.ts