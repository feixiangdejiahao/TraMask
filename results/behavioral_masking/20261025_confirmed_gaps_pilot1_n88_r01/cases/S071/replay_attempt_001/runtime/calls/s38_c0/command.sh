cd /app && python3 - <<'PYEOF'
path = 'src/error-stack.test.ts'
with open(path) as f:
    src = f.read()
old = """    expect(processStackString(crlf, normalize({ mode: 'string' }))).toBe(
      'Error: boom\\r\\n    at a (/app/a.ts:1:1)\\r\\n    at b (/app/b.ts:2:2)\\r'
    );"""
new = """    expect(processStackString(crlf, normalize({ mode: 'string' }))).toBe(
      'Error: boom\\r\\nat a (/app/a.ts:1:1)\\r\\nat b (/app/b.ts:2:2)\\r'
    );"""
assert old in src
src = src.replace(old, new)
with open(path, 'w') as f:
    f.write(src)
print('fixed')
PYEOF
npx vitest run src/error-stack.test.ts 2>&1 | tail -20