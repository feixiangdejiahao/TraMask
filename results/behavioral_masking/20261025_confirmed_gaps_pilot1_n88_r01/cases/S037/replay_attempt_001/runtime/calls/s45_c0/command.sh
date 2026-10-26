cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()
# Fix map/set method calls
s=s.replace("          const result = target[prop](...args)", "          const result = (target[prop] as any)(...args)")
s=s.replace("          return target.has(...args)", "          return (target.has as any)(...args)")
# Fix logic.selector possibly undefined
s=s.replace("      this.rootRaw = this.engine.logic.selector(state)", "      this.rootRaw = this.engine.logic.selector!(state)")
s=s.replace("      previousRoot = this.logic.selector(previousState)", "      previousRoot = this.logic.selector!(previousState)")
s=s.replace("      nextRoot = this.logic.selector(nextState)", "      nextRoot = this.logic.selector!(nextState)")
open(p,'w').write(s)
print('fixed')
PY
npx tsc --noEmit 2>&1 | head -60