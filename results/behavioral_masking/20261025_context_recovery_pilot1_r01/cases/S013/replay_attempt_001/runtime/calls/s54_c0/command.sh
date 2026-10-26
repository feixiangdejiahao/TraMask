cd /app && python3 - <<'PY'
p='src/awilix.ts'
s=open(p).read()
s=s.replace(
"""  type DisposableResolverOptions,
  RESOLVER,
  aliasTo,""",
"""  type DisposableResolverOptions,
  INITIALIZER,
  RESOLVER,
  aliasTo,""")
open(p,'w').write(s)
print(open(p).read()[-600:])
PY
cd /app && npm run build 2>&1 | tail -8