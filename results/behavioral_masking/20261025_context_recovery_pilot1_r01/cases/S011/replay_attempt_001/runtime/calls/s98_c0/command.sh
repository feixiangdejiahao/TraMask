cd /app && python3 - <<'PYEOF'
p='src/resolvers.ts'
s=open(p).read()
s=s.replace("""  if (opts.initializer) {
    ;(opts as any)[INITIALIZER] = opts.initializer
  }""",
"""  if (opts && opts.initializer) {
    ;(opts as any)[INITIALIZER] = opts.initializer
  }""")
open(p,'w').write(s)
print('done')
PYEOF
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head -20