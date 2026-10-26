cd /app && python3 - <<'PY'
import re
p='src/types.ts'
s=open(p).read()

# Add atomicSelectors to InternalContextOptions
s=s.replace("  disableAsyncActions: boolean\n  // ...otherOptions\n}", "  disableAsyncActions: boolean\n  atomicSelectors: boolean\n  // ...otherOptions\n}")

# Add selectorHealth to BuiltLogicAdditions
s=s.replace("  wrapper: LogicWrapper\n}\n\nexport type BuiltLogic", "  wrapper: LogicWrapper\n  /** When atomicSelectors is enabled, returns selector health metadata */\n  selectorHealth?: () => SelectorHealth\n}\n\nexport type BuiltLogic")

# Add selectorHealth to LogicWrapperAdditions
s=s.replace("  extend: <ExtendLogicType extends Logic = LogicType>(\n    extendedInput: LogicInput<ExtendLogicType>,\n  ) => LogicWrapper<ExtendLogicType>\n}\n\nexport type LogicWrapper", "  extend: <ExtendLogicType extends Logic = LogicType>(\n    extendedInput: LogicInput<ExtendLogicType>,\n  ) => LogicWrapper<ExtendLogicType>\n  /** When atomicSelectors is enabled, returns selector health metadata */\n  selectorHealth?: () => SelectorHealth\n}\n\nexport type LogicWrapper")

# Add SelectorHealth type near Selector type
s=s.replace("export type Selector = (state?: any, props?: any) => any\nexport type Props", "export type Selector = (state?: any, props?: any) => any\nexport interface SelectorHealth {\n  selectors: {\n    [name: string]: {\n      dependencies: string[]\n      dependents: string[]\n      evaluations: number\n      dirtyCause: string | null\n    }\n  }\n  topologicalOrder: string[]\n}\nexport type Props")

# Add atomicEngines to Context
s=s.replace("  wrapperContexts: WeakMap<LogicWrapper, WrapperContext>\n  buildHeap: Logic[]", "  wrapperContexts: WeakMap<LogicWrapper, WrapperContext>\n  buildHeap: Logic[]\n  atomicEngines: Map<any, any>")

open(p,'w').write(s)
print("types updated")
PY
grep -n "atomicSelectors\|selectorHealth\|SelectorHealth\|atomicEngines" src/types.ts