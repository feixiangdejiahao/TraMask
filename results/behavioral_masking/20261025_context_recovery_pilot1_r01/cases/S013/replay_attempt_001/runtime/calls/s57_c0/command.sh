cd /app && cat > src/__tests__/container.initialize.test.ts <<'EOF'
import { createContainer } from '../container'
import {
  AwilixInitializationError,
  AwilixNotInitializedError,
  AwilixResolutionError,
} from '../errors'
import { asClass, asFunction } from '../resolvers'

class DatabasePool {
  connected = false
  async connect() {
    this.connected = true
  }
  async disconnect() {
    this.connected = false
  }
}

describe('container.initialize', () => {
  it('initializes a singleton asClass registration with an initializer', async () => {
    const container = createContainer()
    let initCalls = 0
    container.register({
      database: asClass(DatabasePool)
        .singleton()
        .initializer(async (instance) => {
          initCalls++
          await instance.connect()
          return instance
        }),
    })

    expect(() => container.resolve('database')).toThrow(
      AwilixNotInitializedError,
    )

    const result = await container.initialize({ concurrency: 5 })

    expect(typeof result.totalDuration).toBe('number')
    expect(typeof result.metrics.database.duration).toBe('number')
    expect(result.metrics.database.level).toBe(0)
    expect(initCalls).toBe(1)

    const db = container.resolve<DatabasePool>('database')
    expect(db.connected).toBe(true)

    // Idempotent after success.
    const again = await container.initialize()
    expect(again).toBe(result)
    expect(initCalls).toBe(1)
  })

  it('works with asFunction', async () => {
    const container = createContainer()
    container.register({
      value: 42,
      svc: asFunction((deps: any) => deps.value)
        .singleton()
        .initializer(async (instance) => ({
          ...instance,
          initialized: true,
        })),
    })

    const result = await container.initialize()
    expect(result.metrics.svc.level).toBe(0)
    const svc = container.resolve<{ value: number; initialized: boolean }>('svc')
    expect(svc.value).toBe(42)
    expect(svc.initialized).toBe(true)
  })

  it('allows the initializer to return a replacement', async () => {
    const container = createContainer()
    const replacement = { replaced: true }
    let disposedValue: any
    container.register({
      svc: asFunction(() => ({ original: true }))
        .singleton()
        .initializer(() => replacement)
        .disposer((value) => {
          disposedValue = value
        }),
    })

    await container.initialize()
    expect(container.resolve('svc')).toBe(replacement)

    await container.dispose()
    expect(disposedValue).toBe(replacement)
  })

  it('initializes in dependency order using levels', async () => {
    const container = createContainer()
    const order: string[] = []

    container.register({
      b: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          await new Promise((r) => setTimeout(r, 10))
          order.push('b')
        }),
      a: asFunction(({ b }: any) => ({ b }))
        .singleton()
        .initializer(async () => {
          order.push('a')
        }),
    })

    const result = await container.initialize()
    expect(order).toEqual(['b', 'a'])
    expect(result.metrics.b.level).toBe(0)
    expect(result.metrics.a.level).toBe(1)
  })

  it('limits concurrency within a level', async () => {
    const container = createContainer()
    let active = 0
    let maxActive = 0

    const mk = () =>
      asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          active++
          maxActive = Math.max(maxActive, active)
          await new Promise((r) => setTimeout(r, 10))
          active--
        })

    container.register({ a: mk(), b: mk(), c: mk() })

    await container.initialize({ concurrency: 2 })
    expect(maxActive).toBeLessThanOrEqual(2)
    expect(maxActive).toBe(2)
  })

  it('allows services without initializers to be resolved before initialize', () => {
    const container = createContainer()
    container.register({ plain: asFunction(() => 42) })
    expect(container.resolve('plain')).toBe(42)
  })

  it('does not re-initialize parent singletons when a scoped container initializes', async () => {
    const container = createContainer()
    let parentInitCalls = 0
    container.register({
      parentSvc: asFunction(() => ({}))
        .singleton()
        .initializer(async () => {
          parentInitCalls++
        }),
    })

    await container.initialize()
    expect(parentInitCalls).toBe(1)

    const scope = container.createScope()
    let scopeInitCalls = 0
    scope.register({
      scopedSvc: asFunction(() => ({}))
        .scoped()
        .initializer(async () => {
          scopeInitCalls++
        }),
    })

    await scope.initialize()
    expect(parentInitCalls).toBe(1)
    expect(scopeInitCalls).toBe(1)
    expect(scope.resolve('parentSvc')).toBeDefined()
  })

  it('throws AwilixInitializationError with cause when an initializer fails', async () => {
    const container = createContainer()
    const boom = new Error('boom')
    container.register({
      svc: asFunction(() => ({})).singleton().initializer(async () => {
        throw boom
      }),
    })

    let error: unknown
    try {
      await container.initialize()
    } catch (err) {
      error = err
    }

    expect(error).toBeInstanceOf(AwilixInitializationError)
    const initError = error as AwilixInitializationError
    expect(initError.message).toContain('svc')
    expect(initError.message).toContain('boom')
    expect(initError.cause).toBe(boom)
  })

  it('disposes already-initialized services in reverse order on failure', async () => {
    const container = createContainer()
    const disposed: string[] = []
    const fail = new Error('fail')

    container.register({
      a: asFunction(() => ({})).singleton().initializer(async () => {}),
      b: asFunction(({ a }: any) => ({ a }))
        .singleton()
        .initializer(async () => {}),
      c: asFunction(({ b }: any) => ({ b }))
        .singleton()
        .initializer(async () => {
          throw fail
        }),
    })
    container.register({
      aDisposer: asFunction(() => ({})).singleton(),
      bDisposer: asFunction(() => ({})).singleton(),
    })

    ;(container.getRegistration('a') as any).dispose = () => {
      disposed.push('a')
    }
    ;(container.getRegistration('b') as any).dispose = () => {
      disposed.push('b')
    }

    await expect(container.initialize()).rejects.toThrow(
      AwilixInitializationError,
    )
    expect(disposed).toEqual(['b', 'a'])
  })

  it('waits for in-flight initializers in a level before rolling back', async () => {
    const container = createContainer()
    const events: string[] = []
    let resolveSlow!: () => void
    const slowGate = new Promise<void>((r) => (resolveSlow = r))

    container.register({
      slow: asFunction(() => ({})).singleton().initializer(async () => {
        events.push('slow-start')
        await slowGate
        events.push('slow-end')
      }),
      fast: asFunction(() => ({})).singleton().initializer(async () => {
        events.push('fast-start')
        throw new Error('fast-fail')
      }),
      later: asFunction(({ slow }: any) => ({ slow }))
        .singleton()
        .initializer(async () => {
          events.push('later')
        }),
    })

    const promise = container.initialize()
    await new Promise((r) => setTimeout(r, 10))
    expect(events).toContain('slow-start')
    resolveSlow()
    await expect(promise).rejects.toThrow(AwilixInitializationError)
    expect(events).toContain('slow-end')
    expect(events).not.toContain('later')
  })

  it('ignores disposer errors during rollback', async () => {
    const container = createContainer()
    const boom = new Error('init-boom')
    container.register({
      good: asFunction(() => ({})).singleton().initializer(async () => {}),
      bad: asFunction(() => ({})).singleton().initializer(async () => {
        throw boom
      }),
    })
    ;(container.getRegistration('good') as any).dispose = () => {
      throw new Error('dispose-boom')
    }

    let error: unknown
    try {
      await container.initialize()
    } catch (err) {
      error = err
    }
    expect(error).toBeInstanceOf(AwilixInitializationError)
    expect((error as AwilixInitializationError).cause).toBe(boom)
  })

  it('cannot re-initialize after failure', async () => {
    const container = createContainer()
    container.register({
      svc: asFunction(() => ({})).singleton().initializer(async () => {
        throw new Error('nope')
      }),
    })

    await expect(container.initialize()).rejects.toThrow(
      AwilixInitializationError,
    )
    await expect(container.initialize()).rejects.toThrow(
      /previously failed|Cannot re-initialize/,
    )
  })

  it('throws AwilixResolutionError for cycles without entering a failed state', async () => {
    const container = createContainer()
    container.register({
      a: asFunction(({ b }: any) => ({ b }))
        .singleton()
        .initializer(async () => {}),
      b: asFunction(({ a }: any) => ({ a }))
        .singleton()
        .initializer(async () => {}),
    })

    await expect(container.initialize()).rejects.toThrow(AwilixResolutionError)

    // Must not be a "previously failed" state - initialize can be retried.
    await expect(container.initialize()).rejects.toThrow(AwilixResolutionError)
    await expect(container.initialize()).rejects.not.toThrow(
      /previously failed|Cannot re-initialize/,
    )
  })
})
EOF
echo done