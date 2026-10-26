cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()
old = """    sj.registerErrorStackProcessor('Error', (serialized) => {
      expect(serialized.message).toBe('visit [redacted]');
      expect(serialized.stack).toContain('Error: visit [redacted]');
      return { ...serialized, extra: 'added' };
    });"""
new = """    sj.registerErrorStackProcessor('Error', (serialized) => {
      expect(serialized.message).toBe('visit [redacted]');
      expect(serialized.stack).toContain('Error: visit https://example.com');
      return { ...serialized, extra: 'added' };
    });"""
assert old in src
src = src.replace(old, new)
with open(path, 'w') as f:
    f.write(src)
print('updated')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -30