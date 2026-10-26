cd /app && python3 - <<'PYEOF'
path = 'src/schema/actions/requiredIf.unit.test.ts'
with open(path) as f:
    content = f.read()
old = """    expect(
      (restored.attributes as Record<string, { props: { requiredIf: unknown } }>).details.props
        .requiredIf
    ).toStrictEqual({"""
new = """    expect((restored.attributes as any).details.props.requiredIf).toStrictEqual({"""
assert old in content
content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('patched')
PYEOF
npx tsc --noEmit 2>&1 | head -10 && npx prettier --write src/schema/actions/requiredIf.unit.test.ts >/dev/null && npx vitest run src/schema/actions/requiredIf.unit.test.ts --reporter=dot 2>&1 | tail -8