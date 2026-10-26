cd /app && cat > .tmp-edge2.ts <<'EOF'
import { item, map, string, Table, Entity, UpdateItemCommand, $set } from './src/index.js'
const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })
const sch = item({ pk: string().key(), profile: map({ type: string().enum('x','y'), bio: string().optional().requiredIf('type','x') }) })
sch.check()
const Ent = new Entity({ name: 'E', schema: sch, table, timestamps: false })
const res = Ent.build(UpdateItemCommand).item({ pk: 'x', profile: { [$set]: { type: 'x' } } }).params()
console.log('UpdateExpression:', res.UpdateExpression)
console.log('ToolboxItem:', JSON.stringify(res.ToolboxItem, (k,v)=>typeof v==='bigint'?v.toString():v))
console.log('keys of profile:', Object.keys((res.ToolboxItem as any).profile))
EOF
cd /app && npx tsx .tmp-edge2.ts