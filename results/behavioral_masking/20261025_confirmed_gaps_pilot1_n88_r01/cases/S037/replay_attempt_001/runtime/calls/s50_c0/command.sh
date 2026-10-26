cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()
# add isReducer to interface
s=s.replace("  dirtyCause: string | null\n  inProgress: boolean\n}", "  dirtyCause: string | null\n  inProgress: boolean\n  isReducer?: boolean\n}")
# set isReducer in createReducerSelector
s=s.replace("      dirtyCause: null,\n      inProgress: false,\n    }\n    this.selectors.set(name, meta)\n    return (state: any, props: any) => this.runReducerSelector(name, state, props)", "      dirtyCause: null,\n      inProgress: false,\n      isReducer: true,\n    }\n    this.selectors.set(name, meta)\n    return (state: any, props: any) => this.runReducerSelector(name, state, props)")
# fix callSelector
s=s.replace("    const value = this.runSelector(name, state, props)\n    return session ? session.wrapSelectorResult(name, value) : value", "    const value = meta.isReducer ? this.runReducerSelector(name, state, props) : this.runSelector(name, state, props)\n    return session ? session.wrapSelectorResult(name, value) : value")
open(p,'w').write(s)
print('fixed')
PY
npx tsc --noEmit 2>&1 | head -20