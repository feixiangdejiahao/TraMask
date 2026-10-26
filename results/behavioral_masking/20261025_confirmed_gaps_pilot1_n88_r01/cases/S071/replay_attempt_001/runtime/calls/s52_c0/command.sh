cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()

anchor = """  it('does not run the processor for non-matching classes', () => {"""
addition = """  it('runs the processor once for the top-level error, not for causes', () => {
    const sj = new SuperJSON({
      errorStack: {
        mode: 'string',
        includeCauses: 'deep',
        maxCauseDepth: 3,
      },
    });
    sj.allowErrorProps('stack');
    let calls = 0;
    sj.registerErrorStackProcessor('Error', (serialized) => {
      calls++;
      return serialized;
    });
    const e = new Error('outer', { cause: new Error('inner') });
    sj.serialize(e);
    expect(calls).toBe(1);
  });

"""
assert anchor in src
src = src.replace(anchor, addition + anchor)

with open(path, 'w') as f:
    f.write(src)
print('added')
PYEOF
npx vitest run 2>&1 | tail -18