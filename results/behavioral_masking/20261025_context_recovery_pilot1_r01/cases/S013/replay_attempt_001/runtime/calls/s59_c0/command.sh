cd /app && python3 - <<'PY'
p='src/resolvers.ts'
s=open(p).read()
s=s.replace(
"""export type Initializer<T> = (instance: T) => T | Promise<T>
""",
"""export type Initializer<T> = (instance: T) => any | Promise<any>
""")
open(p,'w').write(s)
print("Initializer type relaxed")
PY
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -80