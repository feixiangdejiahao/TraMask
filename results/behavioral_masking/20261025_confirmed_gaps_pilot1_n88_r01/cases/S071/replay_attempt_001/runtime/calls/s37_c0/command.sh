cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()

# Replace CRLF stack with LF stack
old_stack = """  const stack =
    'Error: boom\\r\\n' +
    '    at alpha (/app/src/alpha.ts:1:1)\\r\\n' +
    '    at beta (node:internal/modules/run_main.js:1:1)\\r\\n' +
    '    at gamma (/app/src/transformer.ts:2:2)\\r\\n' +
    '    at delta (/app/src/delta.ts:3:3)';"""
new_stack = """  const stack =
    'Error: boom\\n' +
    '    at alpha (/app/src/alpha.ts:1:1)\\n' +
    '    at beta (node:internal/modules/run_main.js:1:1)\\n' +
    '    at gamma (/app/src/transformer.ts:2:2)\\n' +
    '    at delta (/app/src/delta.ts:3:3)';"""
assert old_stack in src, "stack not found"
src = src.replace(old_stack, new_stack)

# Insert normalizeNewlines option test after the normalizeStackNewlines test
anchor = """  it('normalizeStackNewlines converts CRLF and CR to LF', () => {
    expect(normalizeStackNewlines('a\\r\\nb\\rc')).toBe('a\\nb\\nc');
  });

"""
new_anchor = anchor + """  it('normalizeNewlines option controls CRLF/CR conversion', () => {
    const crlf = 'Error: boom\\r\\n    at a (/app/a.ts:1:1)\\r\\n    at b (/app/b.ts:2:2)\\r';
    expect(processStackString(crlf, normalize({ mode: 'string' }))).toBe(
      'Error: boom\\r\\n    at a (/app/a.ts:1:1)\\r\\n    at b (/app/b.ts:2:2)\\r'
    );
    expect(
      processStackString(
        crlf,
        normalize({ mode: 'string', normalizeNewlines: true })
      )
    ).toBe('Error: boom\\nat a (/app/a.ts:1:1)\\nat b (/app/b.ts:2:2)');
  });

"""
assert anchor in src
src = src.replace(anchor, new_anchor)

with open(path, 'w') as f:
    f.write(src)
print('written')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -40