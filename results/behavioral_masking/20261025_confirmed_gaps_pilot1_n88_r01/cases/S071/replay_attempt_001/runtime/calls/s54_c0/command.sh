cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()

anchor = """  it('round-trips AggregateError in frames mode', () => {"""
addition = """  it('round-trips AggregateError when errorStack is configured in off mode', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    const e = new AggregateError([new Error('one')], 'agg');
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.name).toBe('AggregateError');
    expect(out.errors).toHaveLength(1);
    expect(out.errors[0].message).toBe('one');
  });

  it('uses the correct annotation per mode', () => {
    const off = new SuperJSON({ errorStack: { mode: 'off' } });
    const string = new SuperJSON({ errorStack: { mode: 'string' } });
    string.allowErrorProps('stack');
    const frames = new SuperJSON({ errorStack: { mode: 'frames' } });
    frames.allowErrorProps('stackFrames');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\\n    at a (/app/a.ts:1:1)';

    const offRes = off.serialize({ e });
    expect((offRes.meta!.values as any).e).toEqual(['Error']);

    const stringRes = string.serialize({ e });
    expect((stringRes.meta!.values as any).e).toEqual(['Error/stack']);

    const framesRes = frames.serialize({ e });
    expect((framesRes.meta!.values as any).e).toEqual(['Error/frames']);
  });

"""
assert anchor in src
src = src.replace(anchor, addition + anchor)

with open(path, 'w') as f:
    f.write(src)
print('added')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -20