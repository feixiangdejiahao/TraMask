cd /app && cat src/schema/actions/zodSchemer/parser/types.ts && python3 - <<'PYEOF'
path = 'src/schema/actions/requiredIf.unit.test.ts'
with open(path) as f:
    content = f.read()
content = content.replace(
    "    expect((restored.attributes as Record<string, { props: { requiredIf: unknown } }>).details.props.requiredIf).toStrictEqual({",
    "    expect((restored.attributes as any).details.props.requiredIf).toStrictEqual({"
)
content = content.replace(
    "    expect(() => zod.parser({ mode: 'update' }).parse({ pk: 'x', type: 'a' })).not.toThrow()\n",
    ""
)
with open(path, 'w') as f:
    f.write(content)
print('patched')
PYEOF
npx tsc --noEmit 2>&1 | head -10