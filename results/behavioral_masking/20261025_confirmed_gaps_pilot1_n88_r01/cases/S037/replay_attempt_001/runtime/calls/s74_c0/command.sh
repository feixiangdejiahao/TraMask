cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()
# createReducerSelector wrapper
s=s.replace("    this.selectors.set(name, meta)\n    return (state: any, props: any) => this.runReducerSelector(name, state, props)", "    this.selectors.set(name, meta)\n    return (state: any, props: any = this.logic.props) => this.runReducerSelector(name, state, props)")
# createSelector wrapper
s=s.replace("    this.selectors.set(name, meta)\n    return (state: any, props: any) => this.runSelector(name, state, props)", "    this.selectors.set(name, meta)\n    return (state: any, props: any = this.logic.props) => this.runSelector(name, state, props)")
open(p,'w').write(s)
print('fixed props default')
PY
grep -n "runSelector(name, state, props)" src/core/atomic-selectors.ts | head