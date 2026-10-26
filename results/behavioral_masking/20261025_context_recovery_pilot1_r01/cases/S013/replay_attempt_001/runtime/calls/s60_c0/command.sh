cd /app && python3 - <<'PY'
p='src/__tests__/container.initialize.test.ts'
s=open(p).read()
s=s.replace(
"""import { asClass, asFunction } from '../resolvers'""",
"""import { asClass, asFunction, asValue } from '../resolvers'""")
s=s.replace(
"""    container.register({
      value: 42,
      svc: asFunction((deps: any) => deps.value)""",
"""    container.register({
      value: asValue(42),
      svc: asFunction((deps: any) => deps.value)""")
open(p,'w').write(s)
print("fixed")
PY
cd /app && npx jest src/__tests__/container.initialize.test.ts 2>&1 | tail -80