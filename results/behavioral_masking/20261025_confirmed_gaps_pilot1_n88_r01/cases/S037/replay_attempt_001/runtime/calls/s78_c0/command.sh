cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()
s=s.replace("import { getContext } from '../kea/context'", "import { getContext, getStoreState } from '../kea/context'")
s=s.replace("return (state: any, props: any = this.logic.props) => this.runReducerSelector(name, state, props)", "return (state: any = getStoreState(), props: any = this.logic.props) => this.runReducerSelector(name, state, props)")
s=s.replace("return (state: any, props: any = this.logic.props) => this.runSelector(name, state, props)", "return (state: any = getStoreState(), props: any = this.logic.props) => this.runSelector(name, state, props)")
open(p,'w').write(s)
print('state default added')
PY
npx tsc --noEmit 2>&1 | head -20