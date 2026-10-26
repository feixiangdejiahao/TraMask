cd /app && cat > src/core/atomic-selectors.ts <<'EOF'
import { BuiltLogic, Selector } from '../types'
import { getContext } from '../kea/context'

type DepKind = 'selector' | 'state'

interface AtomicSelectorMeta {
  name: string
  args: Selector[]
  func: (...args: any[]) => any
  dependencies: Set<string>
  depKinds: Map<string, DepKind>
  lastDepVersions: Map<string, number>
  lastArgResults: any[]
  lastPropsVersion: number
  cached: any
  hasCached: boolean
  evaluations: number
  dirtyCause: string | null
  inProgress: boolean
}

interface PendingDep {
  selector: string
  whole: boolean
  paths: Set<string>
}

type Recorder = (path: string) => void

const proxyTargets = new WeakMap<object, any>()

function joinPath(base: string, key: string): string {
  return base ? `${base}.${key}` : key
}

function isTrackableObject(value: any): boolean {
  return value !== null && typeof value === 'object'
}

function registerProxy(proxy: object, target: any): any {
  proxyTargets.set(proxy, target)
  return proxy
}

function unwrap(value: any): any {
  if (value !== null && typeof value === 'object' && proxyTargets.has(value)) {
    return proxyTargets.get(value)
  }
  return value
}

function createObjectProxy(value: any, basePath: string, recorder: Recorder): any {
  const proxy = new Proxy(value, {
    get(target: any, prop: string | symbol, receiver: any) {
      if (typeof prop === 'symbol') {
        return Reflect.get(target, prop, receiver)
      }
      const key = String(prop)
      // Advanced array methods: `.includes()` checks every element.
      if (Array.isArray(target) && key === 'includes') {
        for (let i = 0; i < target.length; i++) {
          recorder(joinPath(basePath, String(i)))
        }
        return target.includes.bind(target)
      }
      // Reading the length depends on the whole collection.
      if (key === 'length') {
        recorder(basePath)
        return target.length
      }
      const result = Reflect.get(target, prop, receiver)
      const childPath = joinPath(basePath, key)
      recorder(childPath)
      if (isTrackableObject(result)) {
        return createProxy(result, childPath, recorder)
      }
      return result
    },
    has(target: any, prop: string | symbol) {
      if (typeof prop === 'symbol') {
        return Reflect.has(target, prop)
      }
      recorder(joinPath(basePath, String(prop)))
      return Reflect.has(target, prop)
    },
  })
  return registerProxy(proxy, value)
}

function createMapProxy(value: Map<any, any>, basePath: string, recorder: Recorder): any {
  const proxy = new Proxy(value, {
    get(target: Map<any, any>, prop: string | symbol, receiver: any) {
      if (typeof prop === 'symbol') {
        return Reflect.get(target, prop, receiver)
      }
      if (prop === 'get' || prop === 'has') {
        return (...args: any[]) => {
          const key = args[0]
          const depPath = joinPath(basePath, `map:${String(key)}`)
          recorder(depPath)
          const result = target[prop](...args)
          if (prop === 'get' && isTrackableObject(result)) {
            return createProxy(result, depPath, recorder)
          }
          return result
        }
      }
      if (prop === 'size') {
        recorder(basePath)
        return target.size
      }
      return Reflect.get(target, prop, receiver)
    },
  })
  return registerProxy(proxy, value)
}

function createSetProxy(value: Set<any>, basePath: string, recorder: Recorder): any {
  const proxy = new Proxy(value, {
    get(target: Set<any>, prop: string | symbol, receiver: any) {
      if (typeof prop === 'symbol') {
        return Reflect.get(target, prop, receiver)
      }
      if (prop === 'has') {
        return (...args: any[]) => {
          recorder(joinPath(basePath, `set:${String(args[0])}`))
          return target.has(...args)
        }
      }
      if (prop === 'size') {
        recorder(basePath)
        return target.size
      }
      return Reflect.get(target, prop, receiver)
    },
  })
  return registerProxy(proxy, value)
}

function createProxy(value: any, basePath: string, recorder: Recorder): any {
  if (value === null || typeof value !== 'object') {
    return value
  }
  if (value instanceof Map) {
    return createMapProxy(value, basePath, recorder)
  }
  if (value instanceof Set) {
    return createSetProxy(value, basePath, recorder)
  }
  return createObjectProxy(value, basePath, recorder)
}

/** Tracks dependencies while a single selector is being evaluated. */
class Session {
  engine: AtomicSelectorEngine
  meta: AtomicSelectorMeta
  stateDeps = new Set<string>()
  pendingDeps = new Map<string, PendingDep>()
  rootRaw: any
  rootProxy: any

  constructor(engine: AtomicSelectorEngine, meta: AtomicSelectorMeta) {
    this.engine = engine
    this.meta = meta
  }

  getRoot(state: any): any {
    if (this.rootProxy === undefined) {
      this.rootRaw = this.engine.logic.selector(state)
      this.rootProxy = createProxy(this.rootRaw, '', (path: string) => this.stateDeps.add(path))
    }
    return this.rootProxy
  }

  recordSelectorDep(name: string): PendingDep {
    let entry = this.pendingDeps.get(name)
    if (!entry) {
      entry = { selector: name, whole: true, paths: new Set() }
      this.pendingDeps.set(name, entry)
    }
    return entry
  }

  wrapSelectorResult(name: string, value: any): any {
    const entry = this.recordSelectorDep(name)
    if (value !== null && typeof value === 'object') {
      return createProxy(value, name, (path: string) => {
        entry.whole = false
        entry.paths.add(path)
      })
    }
    return value
  }
}

function diffPaths(oldVal: any, newVal: any, base: string): string[] {
  if (Object.is(oldVal, newVal)) {
    return []
  }
  if (!isTrackableObject(oldVal) || !isTrackableObject(newVal)) {
    return [base]
  }
  if (oldVal instanceof Map && newVal instanceof Map) {
    const result: string[] = []
    const keys = new Set([...oldVal.keys(), ...newVal.keys()])
    for (const key of keys) {
      const keyPath = joinPath(base, `map:${String(key)}`)
      const oldHas = oldVal.has(key)
      const newHas = newVal.has(key)
      if (!oldHas || !newHas || !Object.is(oldVal.get(key), newVal.get(key))) {
        result.push(keyPath)
      }
      if (oldHas && newHas) {
        const oldValue = oldVal.get(key)
        const newValue = newVal.get(key)
        if (!Object.is(oldValue, newValue) && isTrackableObject(oldValue) && isTrackableObject(newValue)) {
          result.push(...diffPaths(oldValue, newValue, keyPath))
        }
      }
    }
    return result
  }
  if (oldVal instanceof Set && newVal instanceof Set) {
    const result: string[] = []
    for (const value of oldVal) {
      if (!newVal.has(value)) {
        result.push(joinPath(base, `set:${String(value)}`))
      }
    }
    for (const value of newVal) {
      if (!oldVal.has(value)) {
        result.push(joinPath(base, `set:${String(value)}`))
      }
    }
    return result
  }
  if (Array.isArray(oldVal) && Array.isArray(newVal)) {
    const result: string[] = []
    const length = Math.max(oldVal.length, newVal.length)
    for (let i = 0; i < length; i++) {
      if (!Object.is(oldVal[i], newVal[i])) {
        const indexPath = joinPath(base, String(i))
        result.push(indexPath)
        if (isTrackableObject(oldVal[i]) && isTrackableObject(newVal[i])) {
          result.push(...diffPaths(oldVal[i], newVal[i], indexPath))
        }
      }
    }
    return result
  }
  // Plain objects
  const result: string[] = []
  const keys = new Set([...Object.keys(oldVal), ...Object.keys(newVal)])
  for (const key of keys) {
    const oldChild = oldVal[key]
    const newChild = newVal[key]
    if (!Object.is(oldChild, newChild)) {
      const childPath = joinPath(base, key)
      if (isTrackableObject(oldChild) && isTrackableObject(newChild)) {
        result.push(...diffPaths(oldChild, newChild, childPath))
      } else {
        result.push(childPath)
      }
    }
  }
  return result
}

function splitPath(path: string): string[] {
  return path.split('.')
}

function firstSegment(path: string): string {
  const index = path.indexOf('.')
  return index === -1 ? path : path.slice(0, index)
}

export class AtomicSelectorEngine {
  logic: BuiltLogic
  versions = new Map<string, number>()
  selectors = new Map<string, AtomicSelectorMeta>()
  currentSession: Session | null = null
  propsVersion = 0

  constructor(logic: BuiltLogic) {
    this.logic = logic
  }

  createReducerSelector(name: string): Selector {
    const meta: AtomicSelectorMeta = {
      name,
      args: [],
      func: (root: any) => root[name],
      dependencies: new Set(),
      depKinds: new Map(),
      lastDepVersions: new Map(),
      lastArgResults: [],
      lastPropsVersion: 0,
      cached: undefined,
      hasCached: false,
      evaluations: 0,
      dirtyCause: null,
      inProgress: false,
    }
    this.selectors.set(name, meta)
    return (state: any, props: any) => this.runReducerSelector(name, state, props)
  }

  createSelector(name: string, args: Selector[], func: (...args: any[]) => any): Selector {
    const meta: AtomicSelectorMeta = {
      name,
      args,
      func,
      dependencies: new Set(),
      depKinds: new Map(),
      lastDepVersions: new Map(),
      lastArgResults: [],
      lastPropsVersion: 0,
      cached: undefined,
      hasCached: false,
      evaluations: 0,
      dirtyCause: null,
      inProgress: false,
    }
    this.selectors.set(name, meta)
    return (state: any, props: any) => this.runSelector(name, state, props)
  }

  callSelectorFunction(name: string): Selector {
    const engine = this
    const fn = ((state: any, props: any) => engine.callSelector(name, state, props)) as Selector & {
      _atomicSelectorName: string
    }
    fn._atomicSelectorName = name
    return fn
  }

  callSelector(name: string, state: any, props: any): any {
    const session = this.currentSession
    const meta = this.selectors.get(name)
    if (!meta) {
      const value = this.logic.selectors[name](state, props)
      return session ? session.wrapSelectorResult(name, value) : value
    }
    const value = this.runSelector(name, state, props)
    return session ? session.wrapSelectorResult(name, value) : value
  }

  private runSelector(name: string, state: any, props: any): any {
    const meta = this.selectors.get(name)
    if (!meta) {
      throw new Error(`[KEA] Atomic selector "${name}" not found`)
    }
    if (meta.inProgress) {
      throw new Error('[KEA] Circular dependency detected')
    }
    const session = new Session(this, meta)
    const previousSession = this.currentSession
    this.currentSession = session
    meta.inProgress = true
    try {
      const argResults = meta.args.map((arg) => {
        const argName = (arg as any)._atomicSelectorName
        if (argName) {
          return this.callSelector(argName, state, props)
        }
        return arg(state, props)
      })

      const { dirty, cause } = this.checkDirty(meta)
      let finalDirty = dirty
      let finalCause = cause

      // Selectors that are not part of this engine (e.g. connected values) can not
      // be tracked leaf-by-leaf, so compare their whole result instead.
      for (let i = 0; i < meta.args.length; i++) {
        const argName = (meta.args[i] as any)._atomicSelectorName
        if (argName && !this.selectors.has(argName)) {
          if (!Object.is(meta.lastArgResults[i], argResults[i])) {
            finalDirty = true
            if (!finalCause) {
              finalCause = `selector:${argName}`
            }
          }
        }
      }

      if (!finalDirty && meta.hasCached) {
        return meta.cached
      }

      const result = meta.func(...argResults)
      const rawResult = unwrap(result)
      this.commitDeps(meta, session)
      this.propagate(meta, meta.hasCached ? meta.cached : undefined, rawResult)
      meta.cached = rawResult
      meta.hasCached = true
      meta.evaluations += 1
      meta.dirtyCause = finalCause
      meta.lastArgResults = argResults.map(unwrap)
      meta.lastPropsVersion = this.propsVersion
      for (const dep of meta.dependencies) {
        meta.lastDepVersions.set(dep, this.versions.get(dep) ?? 0)
      }
      return rawResult
    } finally {
      meta.inProgress = false
      this.currentSession = previousSession
    }
  }

  private runReducerSelector(name: string, state: any, props: any): any {
    const meta = this.selectors.get(name)
    if (!meta) {
      throw new Error(`[KEA] Atomic reducer selector "${name}" not found`)
    }
    if (meta.inProgress) {
      throw new Error('[KEA] Circular dependency detected')
    }
    const session = new Session(this, meta)
    const previousSession = this.currentSession
    this.currentSession = session
    meta.inProgress = true
    try {
      const { dirty, cause } = this.checkDirty(meta)
      if (!dirty && meta.hasCached) {
        return meta.cached
      }
      const rootProxy = session.getRoot(state)
      const result = rootProxy[name]
      const rawResult = unwrap(result)
      this.commitDeps(meta, session)
      this.propagate(meta, meta.hasCached ? meta.cached : undefined, rawResult)
      meta.cached = rawResult
      meta.hasCached = true
      meta.evaluations += 1
      meta.dirtyCause = cause
      meta.lastPropsVersion = this.propsVersion
      for (const dep of meta.dependencies) {
        meta.lastDepVersions.set(dep, this.versions.get(dep) ?? 0)
      }
      return rawResult
    } finally {
      meta.inProgress = false
      this.currentSession = previousSession
    }
  }

  private checkDirty(meta: AtomicSelectorMeta): { dirty: boolean; cause: string | null } {
    if (!meta.hasCached || meta.lastPropsVersion !== this.propsVersion) {
      return { dirty: true, cause: null }
    }
    for (const dep of meta.dependencies) {
      const current = this.versions.get(dep) ?? 0
      const last = meta.lastDepVersions.get(dep)
      if (last === undefined || current !== last) {
        const kind = meta.depKinds.get(dep)
        return { dirty: true, cause: kind === 'selector' ? `selector:${dep}` : dep }
      }
    }
    return { dirty: false, cause: null }
  }

  private commitDeps(meta: AtomicSelectorMeta, session: Session): void {
    const dependencies = new Set<string>()
    const depKinds = new Map<string, DepKind>()
    for (const path of session.stateDeps) {
      dependencies.add(path)
      depKinds.set(path, 'state')
    }
    for (const entry of session.pendingDeps.values()) {
      if (entry.paths.size === 0) {
        dependencies.add(entry.selector)
        depKinds.set(entry.selector, 'selector')
      } else {
        for (const path of entry.paths) {
          dependencies.add(path)
          depKinds.set(path, 'state')
        }
      }
    }
    meta.dependencies = dependencies
    meta.depKinds = depKinds
  }

  private propagate(meta: AtomicSelectorMeta, oldVal: any, newVal: any): void {
    if (Object.is(oldVal, newVal)) {
      return
    }
    const changes = diffPaths(oldVal, newVal, meta.name)
    for (const change of changes) {
      this.bumpPath(change)
    }
  }

  private bumpPath(path: string): void {
    const parts = splitPath(path)
    let current = ''
    for (const part of parts) {
      current = current ? `${current}.${part}` : part
      this.versions.set(current, (this.versions.get(current) ?? 0) + 1)
    }
  }

  notify(previousState: any, nextState: any): void {
    if (previousState === nextState) {
      return
    }
    const { mount } = getContext()
    if (!mount.counter[this.logic.pathString]) {
      return
    }
    let previousRoot: any
    let nextRoot: any
    try {
      previousRoot = this.logic.selector(previousState)
      nextRoot = this.logic.selector(nextState)
    } catch (e) {
      return
    }
    const changes = diffPaths(previousRoot, nextRoot, '')
    for (const change of changes) {
      this.bumpPath(change)
    }
  }

  notifyPropsChanged(): void {
    this.propsVersion += 1
  }

  private buildDependents(): Map<string, Set<string>> {
    const dependents = new Map<string, Set<string>>()
    for (const meta of this.selectors.values()) {
      for (const dep of meta.dependencies) {
        const root = firstSegment(dep)
        if (this.selectors.has(root)) {
          if (!dependents.has(root)) {
            dependents.set(root, new Set())
          }
          dependents.get(root)!.add(meta.name)
        }
      }
    }
    return dependents
  }

  topologicalOrder(): string[] {
    const names = [...this.selectors.keys()]
    const indegree = new Map<string, number>(names.map((name) => [name, 0]))
    const adjacency = new Map<string, string[]>(names.map((name) => [name, []]))
    for (const meta of this.selectors.values()) {
      for (const dep of meta.dependencies) {
        const root = firstSegment(dep)
        if (root !== meta.name && this.selectors.has(root)) {
          adjacency.get(root)!.push(meta.name)
          indegree.set(meta.name, (indegree.get(meta.name) ?? 0) + 1)
        }
      }
    }
    const queue = names.filter((name) => indegree.get(name) === 0).sort()
    const order: string[] = []
    while (queue.length > 0) {
      const current = queue.shift()!
      order.push(current)
      for (const next of adjacency.get(current)!) {
        indegree.set(next, (indegree.get(next) ?? 0) - 1)
        if (indegree.get(next) === 0) {
          queue.push(next)
        }
      }
    }
    if (order.length !== names.length) {
      throw new Error('[KEA] Circular dependency detected')
    }
    return order
  }

  selectorHealth(): {
    selectors: Record<
      string,
      {
        dependencies: string[]
        dependents: string[]
        evaluations: number
        dirtyCause: string | null
      }
    >
    topologicalOrder: string[]
  } {
    const dependents = this.buildDependents()
    const selectors: Record<
      string,
      {
        dependencies: string[]
        dependents: string[]
        evaluations: number
        dirtyCause: string | null
      }
    > = {}
    for (const [name, meta] of this.selectors) {
      selectors[name] = {
        dependencies: [...meta.dependencies].sort(),
        dependents: [...(dependents.get(name) ?? [])].sort(),
        evaluations: meta.evaluations,
        dirtyCause: meta.dirtyCause,
      }
    }
    return { selectors, topologicalOrder: this.topologicalOrder() }
  }
}

export function getAtomicEngine(logic: BuiltLogic): AtomicSelectorEngine {
  const context = getContext()
  let engine = context.atomicEngines.get(logic) as AtomicSelectorEngine | undefined
  if (!engine) {
    engine = new AtomicSelectorEngine(logic)
    context.atomicEngines.set(logic, engine)
  }
  return engine
}

export function notifyAtomicEngines(previousState: any, nextState: any): void {
  if (previousState === nextState) {
    return
  }
  const context = getContext()
  for (const engine of context.atomicEngines.values()) {
    engine.notify(previousState, nextState)
  }
}

export function detectCircularSelectorDependencies(dependencies: Map<string, Set<string>>): void {
  const state = new Map<string, 0 | 1 | 2>()
  const visit = (name: string) => {
    const current = state.get(name)
    if (current === 1) {
      throw new Error('[KEA] Circular dependency detected')
    }
    if (current === 2) {
      return
    }
    state.set(name, 1)
    const deps = dependencies.get(name)
    if (deps) {
      for (const dep of deps) {
        if (dependencies.has(dep)) {
          visit(dep)
        }
      }
    }
    state.set(name, 2)
  }
  for (const name of dependencies.keys()) {
    visit(name)
  }
}
EOF
echo "rewritten"