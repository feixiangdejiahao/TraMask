cd /app && python3 - <<'PYEOF'
path = 'src/entity/actions/update/updateItemParams/updateItemParams.ts'
with open(path) as f:
    content = f.read()

old = """  const ConditionExpression = [
    requiredIfCondition?.ConditionExpression,
    awsOptions.ConditionExpression
  ]
    .filter((condition): condition is string => condition !== undefined)
    .map(condition => `(${condition})`)
    .join(' AND ')"""
new = """  const conditions = [
    requiredIfCondition?.ConditionExpression,
    awsOptions.ConditionExpression
  ].filter((condition): condition is string => condition !== undefined)

  const ConditionExpression =
    conditions.length === 0
      ? undefined
      : conditions.length === 1
        ? conditions[0]
        : conditions.map(condition => `(${condition})`).join(' AND ')"""
assert old in content
content = content.replace(old, new)
content = content.replace(
    "    ...(ConditionExpression !== '' ? { ConditionExpression } : {}),",
    "    ...(ConditionExpression !== undefined ? { ConditionExpression } : {}),"
)
with open(path, 'w') as f:
    f.write(content)
print('patched')
PYEOF
npx vitest run src/entity --reporter=dot 2>&1 | tail -15