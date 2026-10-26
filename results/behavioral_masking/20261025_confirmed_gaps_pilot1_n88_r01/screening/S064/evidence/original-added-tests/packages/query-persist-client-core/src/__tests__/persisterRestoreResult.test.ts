import { describe, expect, test, vi } from 'vitest'
import { QueryClient, QueryObserver, hashKey } from '@tanstack/query-core'
import {
  PERSISTER_KEY_PREFIX,
  experimental_createQueryPersister,
} from '../createPersister'
import type { QueryKey } from '@tanstack/query-core'
import type { StoragePersisterOptions } from '../createPersister'

function getFreshStorage() {
  const storage = new Map()
  return {
    getItem: (key: string) => Promise.resolve(storage.get(key)),
    setItem: (key: string, value: unknown) => {
      storage.set(key, value)
      return Promise.resolve()
    },
    removeItem: (key: string) => {
      storage.delete(key)
      return Promise.resolve()
    },
    entries: () => Promise.resolve(Array.from(storage.entries())),
  }
}

function setupPersister(
  queryKey: QueryKey,
  persisterOptions: StoragePersisterOptions,
) {
  const client = new QueryClient()
  const queryHash = hashKey(queryKey)
  const storageKey = `${PERSISTER_KEY_PREFIX}-${queryHash}`
  const persister = experimental_createQueryPersister(persisterOptions)
  return { client, persister, queryHash, queryKey, storageKey }
}

function persistedQuery(queryKey: QueryKey, state: any) {
  return JSON.stringify({
    buster: '',
    queryHash: hashKey(queryKey),
    queryKey,
    state,
  })
}

function errorState(
  data: any,
  dataUpdatedAt: number,
  error: string,
  errorUpdatedAt: number,
) {
  return {
    data,
    dataUpdateCount: 5,
    dataUpdatedAt,
    error: { message: error },
    errorUpdateCount: 3,
    errorUpdatedAt,
    fetchFailureCount: 2,
    fetchFailureReason: { message: error },
    fetchMeta: null,
    isInvalidated: true,
    status: 'error',
    fetchStatus: 'idle',
  }
}

describe('persister restore result', () => {
  test('prefetchQuery with fine-grained persister restores full query state', async () => {
    const storage = getFreshStorage()
    const { client, persister, storageKey } = setupPersister(['foo'], {
      storage,
      refetchOnRestore: false,
    })
    const dataUpdatedAt = Date.now()
    const errorUpdatedAt = Date.now()

    await storage.setItem(
      storageKey,
      persistedQuery(
        ['foo'],
        errorState('cached', dataUpdatedAt, 'boom', errorUpdatedAt),
      ),
    )

    const queryFn = vi.fn(() => 'fresh')
    await client.prefetchQuery({
      queryKey: ['foo'],
      queryFn,
      persister: persister.persisterFn as any,
    })

    const query = client.getQueryCache().find({ queryKey: ['foo'] })!
    expect(queryFn).not.toHaveBeenCalled()
    expect(query.state.data).toBe('cached')
    expect(query.state.error?.message).toBe('boom')
    expect(query.state.fetchFailureCount).toBe(2)
    expect(query.state.dataUpdatedAt).toBe(dataUpdatedAt)
    expect(query.state.errorUpdatedAt).toBe(errorUpdatedAt)
    expect(query.state.isInvalidated).toBe(true)
    expect(query.state.status).toBe('error')
    expect(query.state.fetchStatus).toBe('idle')
  })

  test('bulk restore preserves full state for multiple queries', async () => {
    const storage = getFreshStorage()
    const { client, persister, queryKey: key1 } = setupPersister(['foo'], {
      storage,
    })
    const key2: QueryKey = ['bar']
    const now = Date.now()

    const state1 = errorState('foo-data', now, 'foo-error', now)
    const state2 = {
      data: { pages: ['bar-page1', 'bar-page2'], pageParams: [0, 10] },
      dataUpdateCount: 2,
      dataUpdatedAt: now,
      error: null,
      errorUpdateCount: 0,
      errorUpdatedAt: 0,
      fetchFailureCount: 0,
      fetchFailureReason: null,
      fetchMeta: null,
      isInvalidated: false,
      status: 'success',
      fetchStatus: 'idle',
    }
    await storage.setItem(
      `${PERSISTER_KEY_PREFIX}-${hashKey(key1)}`,
      persistedQuery(key1, state1),
    )
    await storage.setItem(
      `${PERSISTER_KEY_PREFIX}-${hashKey(key2)}`,
      persistedQuery(key2, state2),
    )

    await persister.restoreQueries(client)

    const q1 = client.getQueryCache().find({ queryKey: key1 })!
    expect(q1.state.data).toBe('foo-data')
    expect(q1.state.error?.message).toBe('foo-error')
    expect(q1.state.fetchFailureCount).toBe(2)
    expect(q1.state.status).toBe('error')
    expect(q1.state.isInvalidated).toBe(true)
    expect(q1.state.fetchStatus).toBe('idle')

    const q2 = client.getQueryCache().find({ queryKey: key2 })!
    expect(q2.state.data).toEqual({
      pages: ['bar-page1', 'bar-page2'],
      pageParams: [0, 10],
    })
    expect(q2.state.status).toBe('success')
  })

  test('bulk restore merges newer live data with newer persisted error metadata', async () => {
    const storage = getFreshStorage()
    const { client, persister, queryKey, storageKey } = setupPersister(
      ['merge'],
      { storage },
    )
    const key = queryKey
    const now = Date.now()

    await client.prefetchQuery({ queryKey: key, queryFn: () => 'live-data' })
    const query = client.getQueryCache().find({ queryKey: key })!
    query.setState({
      dataUpdatedAt: now - 1000,
      dataUpdateCount: 5,
      error: new Error('live-error'),
      errorUpdatedAt: now - 5000,
      fetchFailureCount: 1,
      fetchFailureReason: new Error('live-error'),
      status: 'error',
      isInvalidated: true,
    })

    await storage.setItem(
      storageKey,
      persistedQuery(
        key,
        errorState('persisted-data', now - 2000, 'persisted-error', now - 1000),
      ),
    )

    await persister.restoreQueries(client)

    const restored = client.getQueryCache().find({ queryKey: key })!
    expect(restored.state.data).toBe('live-data')
    expect(restored.state.dataUpdatedAt).toBe(now - 1000)
    expect(restored.state.error?.message).toBe('persisted-error')
    expect(restored.state.errorUpdatedAt).toBe(now - 1000)
    expect(restored.state.fetchFailureCount).toBe(2)
    expect(restored.state.status).toBe('error')
    expect(restored.state.isInvalidated).toBe(true)

    const observer = new QueryObserver(client, {
      queryKey: key,
      queryFn: () => 'live-data',
    })
    const result = observer.getOptimisticResult(
      client.defaultQueryOptions({ queryKey: key, queryFn: () => 'live-data' }),
    )
    expect(result.isRefetchError).toBe(true)
    expect(result.failureCount).toBe(2)
    expect(result.errorUpdatedAt).toBe(now - 1000)
  })

  test('bulk restore keeps newer persisted data when live error is newer', async () => {
    const storage = getFreshStorage()
    const { client, persister, queryKey, storageKey } = setupPersister(
      ['merge2'],
      { storage },
    )
    const key = queryKey
    const now = Date.now()

    await client.prefetchQuery({ queryKey: key, queryFn: () => 'live-data' })
    const query = client.getQueryCache().find({ queryKey: key })!
    query.setState({
      dataUpdatedAt: now - 5000,
      error: new Error('live-error'),
      errorUpdatedAt: now - 1000,
      fetchFailureCount: 4,
      fetchFailureReason: new Error('live-error'),
      status: 'error',
      isInvalidated: true,
    })

    await storage.setItem(
      storageKey,
      persistedQuery(
        key,
        errorState('persisted-data', now - 1000, 'persisted-error', now - 5000),
      ),
    )

    await persister.restoreQueries(client)

    const restored = client.getQueryCache().find({ queryKey: key })!
    expect(restored.state.data).toBe('persisted-data')
    expect(restored.state.dataUpdatedAt).toBe(now - 1000)
    expect(restored.state.error?.message).toBe('live-error')
    expect(restored.state.errorUpdatedAt).toBe(now - 1000)
    expect(restored.state.fetchFailureCount).toBe(4)
    expect(restored.state.status).toBe('error')
  })
})
