cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()
s=s.replace(
"""    let index = 0
    const errors: unknown[] = []
    const workerCount = Math.max(1, Math.min(concurrency, entries.length))
""",
"""    let index = 0
    const errors: unknown[] = []
    const safeConcurrency =
      Number.isFinite(concurrency) && concurrency > 0 ? concurrency : 1
    const workerCount = Math.max(1, Math.min(safeConcurrency, entries.length))
""")
open(p,'w').write(s)
print("runLevel patched")
PY
cd /app && npx tsc -p tsconfig.build.json --noEmit --pretty 2>&1 | head -20; echo "tsc exit: $?"