cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()
s=s.replace("""    const maxWorkers = Math.max(
      1,
      Math.min(concurrency ?? tasks.length, tasks.length),
    )""",
"""    const maxWorkers = Math.max(
      1,
      Math.min(concurrency ?? level.length, level.length),
    )""")
open(p,'w').write(s)
print('fixed')
PYEOF
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head -30