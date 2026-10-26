cd /app && python3 - <<'PYEOF'
p='src/container.ts'
s=open(p).read()
old = """  function dispose(): Promise<void> {
    const entries = Array.from(container.cache.entries())
    container.cache.clear()
    return Promise.all("""
new = """  function dispose(): Promise<void> {
    const entries = Array.from(container.cache.entries())
    container.cache.clear()
    // Disposal invalidates any initialized state for this container.
    initializedRegistrations.clear()
    initializedServices.length = 0
    initializationPromise = null
    initializationResult = null
    initializationError = null
    return Promise.all("""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('done')
PYEOF
npx jest --no-coverage 2>&1 | tail -25