cd /app && python3 - <<'PYEOF'
p='README.md'
s=open(p).read()

# TOC additions
s=s.replace(
"""- [Disposing](#disposing)
- [API](#api)""",
"""- [Disposing](#disposing)
- [Initializing](#initializing)
- [API](#api)""")

s=s.replace(
"""    - [`container.build()`](#containerbuild)
    - [`container.dispose()`](#containerdispose)""",
"""    - [`container.build()`](#containerbuild)
    - [`container.initialize()`](#containerinitialize)
    - [`container.dispose()`](#containerdispose)""")

# Add Initializing section before # API
init_section = '''
# Initializing

As of Awilix v13, you can use `container.initialize()` to asynchronously
initialize registrations that have an initializer configured. Initialization is
dependency-aware: services are organized into levels, all services in a level
must complete before the next level starts, and services within a level are
initialized in parallel.

```js
import { createContainer, asClass } from 'awilix'

class DatabasePool {
  async connect() {
    // ...
  }
}

const container = createContainer().register({
  database: asClass(DatabasePool)
    .singleton()
    .initializer(async (instance) => {
      await instance.connect()
      return instance
    }),
  userService: asClass(UserService)
    .singleton()
    .initializer(async (instance) => {
      await instance.bootstrap()
      return instance
    }),
})

const result = await container.initialize({ concurrency: 5 })
console.log(result.totalDuration)
console.log(result.metrics.database.duration)
console.log(result.metrics.database.level)
```

The initializer receives the resolved instance and may return a replacement. If
an initializer throws or rejects, all already-initialized services are disposed
in reverse order (in-flight initializers in the failing level are allowed to
complete first), and `initialize()` cannot be retried after a failure. Scoped
containers can be initialized independently, and parent singletons are not
reinitialized.

# API
'''
s=s.replace("\n# API\n", init_section)

# Add container.initialize API subsection before container.dispose
init_api = '''### `container.initialize()`

Initializes all registrations with an initializer, respecting the dependency
graph. Returns a promise resolving to an object with `totalDuration` and a
`metrics` record keyed by registration name, each containing `duration` and
`level`.

```js
const result = await container.initialize({ concurrency: 5 })
```

'''
s=s.replace("### `container.dispose()`", init_api + "### `container.dispose()`")

open(p,'w').write(s)
print('README updated')
PYEOF
npx prettier --write README.md >/dev/null 2>&1
git diff --stat