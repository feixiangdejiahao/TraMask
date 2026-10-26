cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()

# Add tests after the 'off mode never serializes stack even when allowed' test
anchor = """  it('off mode never serializes stack even when allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    sj.allowErrorProps('stack');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\\n    at a (/app/a.ts:1:1)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stack).toBeUndefined();
  });
"""
addition = anchor + """
  it('off mode never serializes stackFrames even when allowed', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'off' } });
    sj.allowErrorProps('stackFrames');
    const e: any = new Error('hello');
    e.stackFrames = [{ raw: 'Error: hello' }];
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stackFrames).toBeUndefined();
  });

  it('string mode does not serialize stackFrames', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'string' } });
    sj.allowErrorProps('stack', 'stackFrames');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\\n    at a (/app/a.ts:1:1)';
    e.stackFrames = [{ raw: 'should not appear' }];
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stack).toBe('Error: hello\\nat a (/app/a.ts:1:1)');
    expect(out.stackFrames).toBeUndefined();
  });

  it('frames mode does not serialize stack', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stack', 'stackFrames');
    const e: any = new Error('hello');
    e.stack = 'Error: hello\\n    at a (/app/a.ts:1:1)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.stackFrames).toEqual([
      { raw: 'Error: hello' },
      { raw: 'at a (/app/a.ts:1:1)' },
    ]);
    expect(out.stack).toBeUndefined();
  });
"""
assert anchor in src
src = src.replace(anchor, addition)

# Add raw options tests near process functions
anchor2 = """  it('frames output starts with the header as the first raw entry', () => {
    const options = normalize({ mode: 'frames' });
    const frames = processStackFrames(stack, options);
    expect(frames[0]).toEqual({ raw: 'Error: boom' });
    expect(frames.length).toBe(5);
  });
"""
addition2 = anchor2 + """
  it('accepts raw (non-normalized) options', () => {
    const raw = { mode: 'string', maxStackLines: 2 } as ErrorStackOptions;
    expect(processStackString(stack, raw)).toBe(
      'Error: boom\\nat alpha (/app/src/alpha.ts:1:1)'
    );
    const rawFrames = { mode: 'frames', maxStackLines: 2 } as ErrorStackOptions;
    expect(processStackFrames(stack, rawFrames)).toEqual([
      { raw: 'Error: boom' },
      { raw: 'at alpha (/app/src/alpha.ts:1:1)' },
    ]);
  });
"""
assert anchor2 in src
src = src.replace(anchor2, addition2)

# Add non-Error cause in direct mode and AggregateError frames round trip after existing cause tests
anchor3 = """  it('drops non-Error causes', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'deep' },
    });
    sj.allowErrorProps('stack');
    const e: any = new Error('outer');
    e.cause = 'not an error';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause).toBeUndefined();
  });
"""
addition3 = anchor3 + """
  it('drops non-Error causes in direct mode', () => {
    const sj = new SuperJSON({
      errorStack: { mode: 'string', includeCauses: 'direct' },
    });
    sj.allowErrorProps('stack');
    const e: any = new Error('outer');
    e.cause = 'not an error';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.cause).toBeUndefined();
  });

  it('round-trips AggregateError in frames mode', () => {
    const sj = new SuperJSON({ errorStack: { mode: 'frames' } });
    sj.allowErrorProps('stackFrames');
    const e: any = new AggregateError(
      [new Error('one'), new TypeError('two')],
      'agg'
    );
    e.stack = 'AggregateError: agg\\n    at a (/app/a.ts:1:1)';
    const out = sj.parse(sj.stringify(e)) as any;
    expect(out.errors).toHaveLength(2);
    expect(out.errors[0].message).toBe('one');
    expect(out.stackFrames[0]).toEqual({ raw: 'AggregateError: agg' });
  });
"""
assert anchor3 in src
src = src.replace(anchor3, addition3)

with open(path, 'w') as f:
    f.write(src)
print('tests added')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -30