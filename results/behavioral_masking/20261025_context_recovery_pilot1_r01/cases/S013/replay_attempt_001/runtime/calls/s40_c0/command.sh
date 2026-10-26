cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()
s=s.replace(
"""  function dispose(): Promise<void> {
    const entries = Array.from(container.cache.entries())
    container.cache.clear()
    return Promise.all(
      entries.map(([, entry]) => {
        const { resolver, value } = entry
        const disposable = resolver as DisposableResolver<any>
        if (disposable.dispose) {
          return Promise.resolve().then(() => disposable.dispose!(value))
        }
        return Promise.resolve()
      }),
    ).then(() => undefined)
  }
}""",
"""  function dispose(): Promise<void> {
    const entries = Array.from(container.cache.entries())
    container.cache.clear()
    initializedValues.clear()
    initializationState = { status: 'idle' }
    return Promise.all(
      entries.map(([, entry]) => {
        const { resolver, value } = entry
        const disposable = resolver as DisposableResolver<any>
        if (disposable.dispose) {
          return Promise.resolve().then(() => disposable.dispose!(value))
        }
        return Promise.resolve()
      }),
    ).then(() => undefined)
  }
}""")
open(p,'w').write(s)
print("dispose patched")
PY
cd /app && npx tsc -p tsconfig.json --noEmit --pretty 2>&1 | head -80