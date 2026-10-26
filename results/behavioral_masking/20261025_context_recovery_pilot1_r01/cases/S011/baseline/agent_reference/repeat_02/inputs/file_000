import { createContainer, asFunction } from '../awilix'

describe('container.initialize', () => {
  it('scope initializing a parent singleton marks it initialized for the root too', async () => {
    let runs = 0
    const container = createContainer()
    container.register({
      db: asFunction((): any => ({}))
        .singleton()
        .initializer(async (instance: any) => {
          runs++
          return instance
        }),
    })

    const scope = container.createScope()
    await scope.initialize()
    expect(runs).toBe(1)
    expect(container.resolve('db')).toBeDefined()

    // Root initialize should not reinitialize the already-initialized singleton.
    const result = await container.initialize()
    expect(runs).toBe(1)
    expect(Object.keys(result.metrics)).toEqual([])
  })
})
