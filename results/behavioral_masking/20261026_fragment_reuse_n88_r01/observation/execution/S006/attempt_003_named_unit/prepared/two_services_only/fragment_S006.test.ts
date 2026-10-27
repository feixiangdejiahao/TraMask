import { createContainer } from '../container'
import { asFunction } from '../resolvers'

describe('container.initialize', () => {
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

    container.register({ a: mk(), b: mk() })

    await container.initialize({ concurrency: 2 })
    expect(maxActive).toBeLessThanOrEqual(2)
    expect(maxActive).toBe(2)
  })
})
