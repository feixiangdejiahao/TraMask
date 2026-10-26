cd /app && python3 - <<'PYEOF'
p='src/__tests__/initialize.test.ts'
s=open(p).read()
s=s.replace("""        .initializer(async () => {
          dbRuns++
        }),""",
"""        .initializer(async (instance: any) => {
          dbRuns++
          return instance
        }),""")
open(p,'w').write(s)
print('fixed')
PYEOF
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -30