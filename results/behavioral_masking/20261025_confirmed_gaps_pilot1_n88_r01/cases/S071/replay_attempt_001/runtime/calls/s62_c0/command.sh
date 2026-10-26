cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()

anchor = """  it('stops cleanly on circular cause chains', () => {"""
addition = """  it('round-trips an AggregateError as a deep cause', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'deep', maxCauseDepth: 2 },
    });
    sj.allowErrorProps('stack');
    const e = new Error('outer', {
      cause: new AggregateError([new Error('inner')], 'aggregated'),
    });
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause).toBeInstanceOf(Error);
    expect(out.cause.name).toBe('AggregateError');
    expect(out.cause.errors).toHaveLength(1);
    expect(out.cause.errors[0].message).toBe('inner');
  });

"""
assert anchor in src
src = src.replace(anchor, addition + anchor)

with open(path, 'w') as f:
    f.write(src)
print('added')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -12