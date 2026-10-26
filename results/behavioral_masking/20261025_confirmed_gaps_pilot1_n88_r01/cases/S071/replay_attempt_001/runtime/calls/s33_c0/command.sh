cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()

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
assert old_stack in src
src = src.replace(old_stack, new_stack)

# Add a normalizeNewlines option test after the normalizeStackNewlines test
old_norm_test = """  it('normalizeStackNewlines converts CRLF and CR to LF', () => {
    expect(normalizeStackNewlines('a\\r\\nb\\rc')).toBe('a\\n\\nb\\nc');
  });"""
# Actual content might differ; let's find it.
print("has norm test:", "normalizeStackNewlines converts" in src)
PYEOF