cd /app && python3 - <<'PY'
p='src/errors.ts'
s=open(p).read()
old = """  constructor(name: string | symbol, cause: Error) {
    super(`Failed to initialize '${name.toString()}': ${cause.message}`)
    this.cause = cause
  }"""
new = """  constructor(name: string | symbol, cause: Error) {
    const causeMessage =
      cause instanceof Error ? cause.message : String(cause)
    super(`Failed to initialize '${name.toString()}': ${causeMessage}`)
    this.cause = cause
  }"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("errors patched")
PY
cd /app && npx tsc -p tsconfig.build.json --noEmit --pretty 2>&1 | head; echo "tsc: $?"