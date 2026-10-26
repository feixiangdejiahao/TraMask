cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()
s=s.replace("""import * as util from 'util'
import { performance } from 'perf_hooks'
""", """import * as util from 'util'
""")
s=s.replace("performance.now()", "now()")
# add now helper before getErrorMessage
s=s.replace(
"""  /**
   * Returns the message of an unknown error, falling back to String(err).
   */
  function getErrorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err)
  }""",
"""  /**
   * Returns the message of an unknown error, falling back to String(err).
   */
  function getErrorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err)
  }

  /**
   * Returns a high-resolution timestamp if available, falling back to
   * `Date.now()` in environments without `performance`.
   */
  function now(): number {
    const perf = (globalThis as {
      performance?: { now(): number }
    }).performance
    return perf && typeof perf.now === 'function' ? perf.now() : Date.now()
  }""")
open(p,'w').write(s)
print('replaced')
PYEOF
npx tsc -p tsconfig.json --noEmit --pretty false 2>&1 | grep -v "examples/typescript" | head -20