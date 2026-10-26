cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()
old = """  // Plain objects
  const result: string[] = []
  const keys = new Set([...Object.keys(oldVal), ...Object.keys(newVal)])
  for (const key of keys) {
"""
new = """  // Plain objects (and class instances such as Date)
  const keys = new Set([...Object.keys(oldVal), ...Object.keys(newVal)])
  if (keys.size === 0) {
    return [base]
  }
  const result: string[] = []
  for (const key of keys) {
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('added')
PY
npx tsc --noEmit 2>&1 | head && NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -8