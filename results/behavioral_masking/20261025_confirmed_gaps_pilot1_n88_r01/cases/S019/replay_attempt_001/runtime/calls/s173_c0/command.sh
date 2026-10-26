cd /app && python3 - <<'PYEOF'
path = 'src/schema/actions/requiredIf.unit.test.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "    const { Item } = entity.build(PutItemCommand).item({ pk: 'x', type: 'a' }).params()\n    expect(Item.details).toBe('default')",
    "    const res = entity.build(PutItemCommand).item({ pk: 'x', type: 'a' }).params()\n    expect((res as { Item: Record<string, unknown> }).Item.details).toBe('default')"
)
content = content.replace(
    "    expect(restored.attributes.details.props.requiredIf).toStrictEqual({",
    "    expect((restored.attributes as Record<string, { props: { requiredIf: unknown } }>).details.props.requiredIf).toStrictEqual({"
)
with open(path, 'w') as f:
    f.write(content)
print('patched')
PYEOF
npx tsc --noEmit 2>&1 | head -10 && npx prettier --write src/schema/actions/requiredIf.unit.test.ts >/dev/null && npx vitest run src/schema/actions/requiredIf.unit.test.ts --reporter=dot 2>&1 | tail -8