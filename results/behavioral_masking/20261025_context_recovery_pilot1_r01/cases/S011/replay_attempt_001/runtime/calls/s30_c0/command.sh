cat > src/__tests__/initialize.test.ts <<'EOF'
import {
  createContainer,
  asClass,
  asFunction,
  AwilixInitializationError,
  AwilixNotInitializedError,
  AwilixResolutionError,
  InjectionMode,
} from '../awilix'

class DatabasePool {
  connected = false
  disposeCalls = 0
  async connect() {
    this.connected = true
  }
  async dispose() {
    this.disposeCalls++
  }
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

describe('container.initialize', () => {
  it('initializes a singleton with an initializer and returns metrics', async () => {
    const container = createContainer()
    const db = new DatabasePool()
    container.register({
      database: asFunction(() => db)
        .singleton()
        .initializer(async (instance) => {
          await instance.connect()
          return instance
        }),
    })

    const result = await container.initialize()
    expect(db.connected).toBe(true)
    expect(typeof result.totalDuration).toBe('number')
    expect(result.metrics.database.duration).toBeGreaterThanOrEqual(0)
    expect(result.metrics.database.level).toBe(0)
    expect(container.resolve('database')).toBe(db)
  })

  it('supports initializer with asClass and replacement return', async () => {
    const container = createContainer()
    const original = new DatabasePool()
    const replacement = new DatabasePool()
    container.register({
      database: asClass(() => original as any)
        .singleton()
        .initializer(async () => {
          replacement.connected = true
          return replacement
        }),
    })

    await container.initialize()
    expect(container.resolve('database')).toBe(replacement)
    expect(replacement.connected).toBe(true)
  })

  it('initializes dependencies in level order', async () => {
    const order: string[] = []
    const container = createContainer()
    container.register({
      db: asFunction(() => ({}))
        .singleton()
        .initializer(async (instance: any) => {
          instance.ready = true
          await delay(10)
          order.push('db')
          return instance
        }),
      service: asFunction(({ db }: any) => ({ db }))
        .singleton()
        .initializer(async (instance: any) => {
          order.push('service')
          expect(instance.db.ready).toBe(true)
          return instance
        }),
    })

    const result = await container.initialize()
    expect(order).toEqual(['db', 'service'])
    expect(result.metrics.db.level).toBe(0)
    expect(result.metrics.service.level).toBe(1)
  })

  it('runs independent services within a level in parallel', async () => {
    let concurrent = 0
    let maxConcurrent = 0
    const container = createContainer()
    container.register({
      a: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          concurrent++
          maxConcurrent = Math.max(maxConcurrent, concurrent)
          await delay(50)
          concurrent--
        }),
      b: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          concurrent++
          maxConcurrent = Math.max(maxConcurrent, concurrent)
          await delay(50)
          concurrent--
        }),
    })

    await container.initialize()
    expect(maxConcurrent).toBe(2)
  })

  it('limits concurrency within a level', async () => {
    let concurrent = 0
    let maxConcurrent = 0
    const container = createContainer()
    const names = ['a', 'b', 'c', 'd']
    for (const name of names) {
      container.register({
        [name]: asFunction(() => ({}))
          .singleton()
          .initializer(async () => {
            concurrent++
            maxConcurrent = Math.max(maxConcurrent, concurrent)
            await delay(30)
            concurrent--
          }),
      })
    }

    await container.initialize({ concurrency: 2 })
    expect(maxConcurrent).toBe(2)
  })

  it('is idempotent after success', async () => {
    let runs = 0
    const container = createContainer()
    container.register({
      a: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          runs++
        }),
    })

    const first = await container.initialize()
    const second = await container.initialize()
    expect(runs).toBe(1)
    expect(second).toBe(first)
  })

  it('throws AwilixNotInitializedError when resolving an uninitialized service', async () => {
    const container = createContainer()
    container.register({
      a: asFunction(() => ({}))
        .singleton()
        .initializer(async () => ({})),
    })

    let error: any
    try {
      container.resolve('a')
    } catch (err) {
      error = err
    }
    expect(error).toBeInstanceOf(AwilixNotInitializedError)
    expect(error.message).toContain('not initialized')
  })

  it('allows resolving services without initializers before initialize()', () => {
    const container = createContainer()
    container.register({ a: asFunction(() => 42) })
    expect(container.resolve('a')).toBe(42)
  })

  it('throws AwilixInitializationError with name, message and cause on failure', async () => {
    const container = createContainer()
    const boom = new Error('boom happened')
    container.register({
      a: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          throw boom
        }),
    })

    let error: any
    try {
      await container.initialize()
    } catch (err) {
      error = err
    }
    expect(error).toBeInstanceOf(AwilixInitializationError)
    expect(error.message).toContain('a')
    expect(error.message).toContain('boom happened')
    expect(error.cause).toBe(boom)
  })

  it('rolls back initialized services in reverse order on failure', async () => {
    const order: string[] = []
    const container = createContainer()
    container.register({
      a: asFunction(() => ({}))
        .singleton()
        .disposer(() => {
          order.push('a')
        })
        .initializer(async () => ({})),
      b: asFunction(() => ({}))
        .singleton()
        .disposer(() => {
          order.push('b')
        })
        .initializer(async () => ({})),
      c: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          throw new Error('c failed')
        }),
    })

    await expect(container.initialize()).rejects.toBeInstanceOf(
      AwilixInitializationError,
    )
    expect(order).toEqual(['b', 'a'])
  })

  it('allows in-flight initializers to complete before rollback', async () => {
    const events: string[] = []
    const container = createContainer()
    container.register({
      a: asFunction(() => ({}))
        .singleton()
        .disposer(() => {
          events.push('dispose a')
        })
        .initializer(async () => {
          await delay(80)
          events.push('initialized a')
        }),
      b: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          await delay(10)
          events.push('failed b')
          throw new Error('b failed')
        }),
    })

    await expect(container.initialize()).rejects.toBeInstanceOf(
      AwilixInitializationError,
    )
    expect(events).toContain('initialized a')
    expect(events.indexOf('initialized a')).toBeLessThan(
      events.indexOf('dispose a'),
    )
  })

  it('cannot re-initialize after failure', async () => {
    const container = createContainer()
    container.register({
      a: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          throw new Error('nope')
        }),
    })

    await expect(container.initialize()).rejects.toBeInstanceOf(
      AwilixInitializationError,
    )
    let error: any
    try {
      await container.initialize()
    } catch (err) {
      error = err
    }
    expect(error.message).toMatch(/previously failed|Cannot re-initialize/)
  })

  it('throws AwilixResolutionError for circular dependencies and can be retried', async () => {
    const container = createContainer()
    container.register({
      a: asFunction(({ b }: any) => ({ b }))
        .singleton()
        .initializer(async () => ({})),
      b: asFunction(({ a }: any) => ({ a }))
        .singleton()
        .initializer(async () => ({})),
    })

    await expect(container.initialize()).rejects.toBeInstanceOf(
      AwilixResolutionError,
    )

    // Remove the cycle and retry - should succeed.
    container.register({
      b: asFunction(() => ({}))
        .singleton()
        .initializer(async () => ({})),
    })
    await expect(container.initialize()).resolves.toBeDefined()
  })

  it('scoped containers initialize independently without reinitializing parent singletons', async () => {
    let dbRuns = 0
    let scopedRuns = 0
    const container = createContainer()
    container.register({
      db: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          dbRuns++
        }),
    })
    await container.initialize()

    const scope = container.createScope()
    scope.register({
      scoped: asFunction(() => ({}))
        .scoped()
        .initializer(async () => {
          scopedRuns++
        }),
    })

    const result = await scope.initialize()
    expect(dbRuns).toBe(1)
    expect(scopedRuns).toBe(1)
    expect(result.metrics.scoped.level).toBe(0)
    // Parent singleton is visible and considered initialized from the scope.
    expect(scope.resolve('db')).toBeDefined()
  })

  it('classic injection mode also works', async () => {
    const container = createContainer({ injectionMode: InjectionMode.CLASSIC })
    const order: string[] = []
    container.register({
      db: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          order.push('db')
        }),
      service: asFunction((db: any) => ({ db }))
        .singleton()
        .initializer(async () => {
          order.push('service')
        }),
    })

    await container.initialize()
    expect(order).toEqual(['db', 'service'])
  })
})
EOF
npx jest src/__tests__/initialize.test.ts --no-coverage 2>&1 | tail -80