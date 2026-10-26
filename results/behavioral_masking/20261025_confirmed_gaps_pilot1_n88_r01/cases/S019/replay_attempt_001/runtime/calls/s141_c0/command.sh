cd /app && python3 - <<'PYEOF'
path = 'src/entity/actions/update/updateItemParams/requiredIfConditions.ts'
with open(path) as f:
    content = f.read()

# change conditions array to Set-like: keep array but check includes before push
old = "      const tokens = pathTokens(subSchema.transformedPath.arrayPath, state)\n      state.conditions.push(`attribute_exists(${tokens})`)"
new = "      const tokens = pathTokens(subSchema.transformedPath.arrayPath, state)\n      const condition = `attribute_exists(${tokens})`\n      if (!state.conditions.includes(condition)) {\n        state.conditions.push(condition)\n      }"
assert old in content
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('patched')
PYEOF
cd /app && npx tsx .tmp-edge3.ts 2>/dev/null; cat > .tmp-dedup.ts <<'EOF'
import { item, string, Table, Entity, UpdateItemCommand } from './src/index.js'
const table = new Table({ name: 't', partitionKey: { type: 'string', name: 'pk' } })
const sch = item({
  pk: string().key(),
  type: string().enum('a','b'),
  flag: string().optional(),
  details: string().optional().requiredIf('type','a').requiredIf('flag','on')
})
sch.check()
const Ent = new Entity({ name: 'E', schema: sch, table, timestamps: false })
const res = Ent.build(UpdateItemCommand).item({ pk: 'x', type: 'a', flag: 'on' }).params()
console.log(res.ConditionExpression)
EOF
npx tsx .tmp-dedup.ts