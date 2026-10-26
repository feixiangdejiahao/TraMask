cd /app && python3 - <<'PY'
p='src/__tests__/container.initialize.test.ts'
s=open(p).read()
s=s.replace(
"""      svc: asFunction((deps: any) => deps.value)
        .singleton()
        .initializer(async (instance) => ({
          ...instance,
          initialized: true,
        })),""",
"""      svc: asFunction((deps: any) => ({ value: deps.value }))
        .singleton()
        .initializer(async (instance) => ({
          ...instance,
          initialized: true,
        })),""")
open(p,'w').write(s)
print("fixed")
PY
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -30