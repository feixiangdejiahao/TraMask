cd /app && python3 - <<'PY'
p='src/core/atomic-selectors.ts'
s=open(p).read()
old = """    has(target: any, prop: string | symbol) {
      if (typeof prop === 'symbol') {
        return Reflect.has(target, prop)
      }
      recorder(joinPath(basePath, String(prop)))
      return Reflect.has(target, prop)
    },
  })
  return registerProxy(proxy, value)
}
"""
new = """    has(target: any, prop: string | symbol) {
      if (typeof prop === 'symbol') {
        return Reflect.has(target, prop)
      }
      recorder(joinPath(basePath, String(prop)))
      return Reflect.has(target, prop)
    },
    ownKeys(target: any) {
      recorder(basePath)
      return Reflect.ownKeys(target)
    },
    getOwnPropertyDescriptor(target: any, prop: string | symbol) {
      if (typeof prop !== 'symbol') {
        recorder(joinPath(basePath, String(prop)))
      }
      return Object.getOwnPropertyDescriptor(target, prop)
    },
  })
  return registerProxy(proxy, value)
}
"""
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print('added ownKeys')
PY
npx tsc --noEmit 2>&1 | head && NODE_ENV=development BABEL_ENV=test npx jest test/jest/atomic-selectors.js 2>&1 | tail -8