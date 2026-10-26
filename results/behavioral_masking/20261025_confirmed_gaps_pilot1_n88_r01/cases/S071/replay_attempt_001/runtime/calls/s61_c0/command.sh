cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()

anchor = """  it('uses the correct annotation per mode', () => {"""
addition = """  it('still copies non-stack allowed props in off mode', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    sj.allowErrorProps('code');
    const e: any = new Error('hello');
    e.code = 'P2002';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.code).toBe('P2002');
    expect(out.stack).toBeUndefined();
  });

  it('uses Error/stack rule even when stack is not allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    const e: any = new Error('hello');
    e.stack = 'Error: hello\\n    at a (/app/a.ts:1:1)';
    const res = sj.serialize({ e });
    expect((res.meta!.values as any).e).toEqual(['Error/stack']);
    const out = sj.deserialize(res) as any;
    expect(out.e.stack).toBeUndefined();
  });

"""
assert anchor in src
src = src.replace(anchor, addition + anchor)

with open(path, 'w') as f:
    f.write(src)
print('added')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -12