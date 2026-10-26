cd /app && python3 - <<'PY'
p='src/container.ts'
s=open(p).read()

s=s.replace(
"""import {
  BuildResolverOptions,
  Constructor,
  DisposableResolver,
  Initializer,
  Resolver,
  asClass,
  asFunction,
} from './resolvers'""",
"""import {
  BuildResolverOptions,
  Constructor,
  DisposableResolver,
  INITIALIZER,
  Initializer,
  Resolver,
  asClass,
  asFunction,
} from './resolvers'""")

# Replace all uses of resolver initializer property checks
s=s.replace("typeof (resolver as any).initializer === 'function'", "typeof (resolver as any)[INITIALIZER] === 'function'")
s=s.replace("(entry.resolver as any)\n                .initializer as Initializer<any>", "(entry.resolver as any)[INITIALIZER] as Initializer<any>")

open(p,'w').write(s)
print("container patched")
PY
grep -n "INITIALIZER\|initializer" src/container.ts | head -30