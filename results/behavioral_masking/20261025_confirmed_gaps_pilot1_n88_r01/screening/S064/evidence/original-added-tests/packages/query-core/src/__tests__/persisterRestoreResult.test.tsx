import { beforeEach, describe, expect, test, vi } from 'vitest'
import {
  QueryCache,
  QueryClient,
  QueryObserver,
  createPersisterRestoreResult,
  isPersisterRestoreResult,
} from '..'
import type { QueryState } from '..'

function state(
  overrides: Partial<QueryState<any, any>> = {},
): QueryState<any, any> {
  return {
    data: undefined,
    dataUpdateCount: 0,
    dataUpdatedAt: 0,
    error: null,
    errorUpdateCount: 0,
    errorUpdatedAt: 0,
    fetchFailureCount: 0,
    fetchFailureReason: null,
    fetchMeta: null,
    isInvalidated: false,
    status: 'pending',
    fetchStatus: 'idle',
    ...overrides,
  }
}

describe('createPersisterRestoreResult', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    queryClient = new QueryClient()
    queryClient.mount()
  })

  test('returns a restored snapshot marker with data and state', () => {
    const snapshot = state({
      data: 'cached',
      status: 'success',
      dataUpdatedAt: 111,
      dataUpdateCount: 3,
    })
    const result = createPersisterRestoreResult({
      data: 'cached',
      state: snapshot,
    })
    expect(result.data).toBe('cached')
    expect(result.state).toBe(snapshot)
    expect(isPersisterRestoreResult(result)).toBe(true)
    expect(isPersisterRestoreResult({ data: 'cached' })).toBe(false)
  })

  test('adopts persisted state when a persister returns a restore result', async () => {
    const onSuccess = vi.fn()
    const onSettled = vi.fn()
    const client = new QueryClient({
      queryCache: new QueryCache({ onSuccess, onSettled }),
    })
    client.mount()
    const key = ['persister-restore']
    const queryFn = vi.fn(() => 'fresh')
    const restoredState = state({
      data: 'cached',
      dataUpdateCount: 7,
      dataUpdatedAt: 111,
      error: new Error('boom'),
      errorUpdateCount: 4,
      errorUpdatedAt: 222,
      fetchFailureCount: 3,
      fetchFailureReason: new Error('boom'),
      fetchMeta: null,
      isInvalidated: true,
      status: 'error',
      fetchStatus: 'idle',
    })

    await client.fetchQuery({
      queryKey: key,
      queryFn,
      persister: () =>
        createPersisterRestoreResult({
          data: 'cached',
          state: restoredState,
        }),
    })

    const query = client.getQueryCache().find({ queryKey: key })!
    expect(queryFn).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()
    expect(onSettled).not.toHaveBeenCalled()
    expect(query.state).toEqual(restoredState)
    expect(query.state.fetchStatus).toBe('idle')
    expect(query.state.status).toBe('error')
    expect(query.state.fetchFailureCount).toBe(3)
    expect(query.state.errorUpdatedAt).toBe(222)
    expect(query.state.isInvalidated).toBe(true)
    expect(query.state.dataUpdateCount).toBe(7)
  })

  test('observer result exposes restored error metadata and isRefetchError', async () => {
    const key = ['persister-restore']
    const restoredState = state({
      data: 'cached',
      dataUpdatedAt: 111,
      error: new Error('boom'),
      errorUpdatedAt: 222,
      fetchFailureCount: 3,
      fetchFailureReason: new Error('boom'),
      isInvalidated: true,
      status: 'error',
    })

    const observer = new QueryObserver(queryClient, {
      queryKey: key,
      queryFn: () => 'fresh',
      persister: () =>
        createPersisterRestoreResult({ data: 'cached', state: restoredState }),
    })

    const unsubscribe = observer.subscribe(() => {})
    await observer.refetch()
    const result = observer.getCurrentResult()
    unsubscribe()

    expect(result.status).toBe('error')
    expect(result.isRefetchError).toBe(true)
    expect(result.failureCount).toBe(3)
    expect(result.failureReason?.message).toBe('boom')
    expect(result.errorUpdatedAt).toBe(222)
    expect(result.dataUpdatedAt).toBe(111)
    expect(result.fetchStatus).toBe('idle')
  })

  test('restore merges data and error freshness independently', async () => {
    const key = ['persister-restore']
    const client = new QueryClient()
    client.mount()
    await client.prefetchQuery({ queryKey: key, queryFn: () => 'live-data' })
    const query = client.getQueryCache().find({ queryKey: key })!

    query.setState({
      dataUpdatedAt: 1000,
      dataUpdateCount: 5,
      error: new Error('live-error'),
      errorUpdatedAt: 100,
      fetchFailureCount: 1,
      fetchFailureReason: new Error('live-error'),
      status: 'error',
      isInvalidated: true,
    })

    query.restore(
      state({
        data: 'persisted-data',
        dataUpdatedAt: 500,
        dataUpdateCount: 2,
        error: new Error('persisted-error'),
        errorUpdatedAt: 2000,
        fetchFailureCount: 9,
        fetchFailureReason: new Error('persisted-error'),
        isInvalidated: false,
        status: 'error',
      }),
    )

    expect(query.state.data).toBe('live-data')
    expect(query.state.dataUpdatedAt).toBe(1000)
    expect(query.state.dataUpdateCount).toBe(5)
    expect(query.state.error?.message).toBe('persisted-error')
    expect(query.state.errorUpdatedAt).toBe(2000)
    expect(query.state.fetchFailureCount).toBe(9)
    expect(query.state.status).toBe('error')
    expect(query.state.isInvalidated).toBe(true)
  })

  test('restore keeps newer persisted data even when live error is newer', async () => {
    const key = ['persister-restore']
    const client = new QueryClient()
    client.mount()
    await client.prefetchQuery({ queryKey: key, queryFn: () => 'live-data' })
    const query = client.getQueryCache().find({ queryKey: key })!

    query.setState({
      dataUpdatedAt: 100,
      error: new Error('live-error'),
      errorUpdatedAt: 2000,
      fetchFailureCount: 4,
      fetchFailureReason: new Error('live-error'),
      status: 'error',
      isInvalidated: true,
    })

    query.restore(
      state({
        data: 'persisted-data',
        dataUpdatedAt: 5000,
        dataUpdateCount: 2,
        error: new Error('persisted-error'),
        errorUpdatedAt: 100,
        fetchFailureCount: 1,
        fetchFailureReason: new Error('persisted-error'),
        status: 'error',
      }),
    )

    expect(query.state.data).toBe('persisted-data')
    expect(query.state.dataUpdatedAt).toBe(5000)
    expect(query.state.error?.message).toBe('live-error')
    expect(query.state.errorUpdatedAt).toBe(2000)
    expect(query.state.fetchFailureCount).toBe(4)
    expect(query.state.status).toBe('error')
  })

  test('infinite query restore preserves pagination state', async () => {
    const key = ['infinite-restore']
    const restoredState = state({
      data: {
        pages: ['page1', 'page2'],
        pageParams: [0, 10],
      },
      dataUpdatedAt: 111,
      dataUpdateCount: 2,
      status: 'success',
    })

    await queryClient.fetchInfiniteQuery({
      queryKey: key,
      queryFn: () => 'fresh',
      initialPageParam: 0,
      getNextPageParam: () => undefined,
      persister: () =>
        createPersisterRestoreResult({
          data: {
            pages: ['page1', 'page2'],
            pageParams: [0, 10],
          },
          state: restoredState,
        }),
    })

    const query = queryClient.getQueryCache().find({ queryKey: key })!
    expect(query.state.data).toEqual({
      pages: ['page1', 'page2'],
      pageParams: [0, 10],
    })
    expect(query.state.fetchStatus).toBe('idle')
  })

  test('restore does not trigger cache success callbacks', () => {
    const onSuccess = vi.fn()
    const onSettled = vi.fn()
    const client = new QueryClient({
      queryCache: new QueryCache({ onSuccess, onSettled }),
    })
    client.mount()
    const key = ['persister-restore']

    client.getQueryCache().build(client, { queryKey: key }).restore(
      state({
        data: 'cached',
        dataUpdatedAt: 111,
        status: 'success',
        dataUpdateCount: 2,
      }),
    )

    expect(onSuccess).not.toHaveBeenCalled()
    expect(onSettled).not.toHaveBeenCalled()
  })
})
