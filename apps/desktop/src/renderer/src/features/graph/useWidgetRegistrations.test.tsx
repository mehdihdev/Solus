import { act, renderHook, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWidgetRegistrations } from './useWidgetRegistrations'
import { reconcileWidgetGraph } from '../../lib/api/widgetGraph'
import { ApiError } from '../../lib/api/envelope.types'
import { useAuthStore } from '../../store/authStore'
import type { Entity } from '../../lib/api/resources'

vi.mock('../../lib/api/widgetGraph', () => ({ reconcileWidgetGraph: vi.fn() }))

const root: Entity = {
  id: 'bench',
  project_id: 'p1',
  type: 'solus:live_bench',
  name: 'Live Bench',
  domain: 'workspace',
  origin: 'system',
  source_key: null
}
const refresh = vi.fn()
beforeEach(() => {
  vi.resetAllMocks()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@example.test' } })
  vi.mocked(reconcileWidgetGraph).mockResolvedValue(undefined)
})

it('waits for the complete ready graph and reconciles missing registration once', async () => {
  let finish!: () => void
  vi.mocked(reconcileWidgetGraph).mockReturnValue(
    new Promise<void>((resolve) => {
      finish = resolve
    })
  )
  const { rerender } = renderHook(
    ({ ready, entities }) => useWidgetRegistrations('p1', ready, entities, refresh),
    { initialProps: { ready: false, entities: null as Entity[] | null } }
  )
  expect(reconcileWidgetGraph).not.toHaveBeenCalled()
  rerender({ ready: true, entities: [] })
  await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1))
  expect(refresh).not.toHaveBeenCalled()
  rerender({ ready: true, entities: [] })
  await act(async () => finish())
  expect(refresh).toHaveBeenCalledTimes(1)
  rerender({ ready: true, entities: [] })
  expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1)
})

it('does not reconcile an actual persisted project registration', () => {
  renderHook(() => useWidgetRegistrations('p1', true, [root], refresh))
  expect(reconcileWidgetGraph).not.toHaveBeenCalled()
})

it('issues only one POST under StrictMode effect replay', async () => {
  renderHook(() => useWidgetRegistrations('p1', true, [], refresh), {
    wrapper: ({ children }) => <StrictMode>{children}</StrictMode>
  })
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
  expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1)
})

it.each([
  { ...root, project_id: 'other' },
  { ...root, origin: 'user' }
])('does not treat an unrelated or non-system node as the registration', async (entity) => {
  renderHook(() => useWidgetRegistrations('p1', true, [entity], refresh))
  await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1))
})

it.each([new ApiError(403, 'FORBIDDEN', 'private message'), new Error('private message')])(
  'requires manual retry after a refusal or failure',
  async (error) => {
    vi.mocked(reconcileWidgetGraph).mockRejectedValueOnce(error)
    const { result, rerender } = renderHook(() => useWidgetRegistrations('p1', true, [], refresh))
    await waitFor(() =>
      expect(result.current.status).toBe(error instanceof ApiError ? 'forbidden' : 'error')
    )
    rerender()
    expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1)
    expect(refresh).not.toHaveBeenCalled()
    act(() => result.current.retry())
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
    expect(reconcileWidgetGraph).toHaveBeenCalledTimes(2)
  }
)

it('invalidates project A-B-A completions and aborts old work', async () => {
  const finishes: (() => void)[] = []
  vi.mocked(reconcileWidgetGraph).mockImplementation(
    () => new Promise<void>((resolve) => finishes.push(resolve))
  )
  const { rerender } = renderHook(
    ({ project }) => useWidgetRegistrations(project, true, [], refresh),
    {
      initialProps: { project: 'p1' }
    }
  )
  await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1))
  rerender({ project: 'p2' })
  await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(2))
  rerender({ project: 'p1' })
  await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(3))
  expect(vi.mocked(reconcileWidgetGraph).mock.calls[0]?.[1]?.aborted).toBe(true)
  await act(async () => finishes[0]!())
  expect(refresh).not.toHaveBeenCalled()
  await act(async () => finishes[2]!())
  expect(refresh).toHaveBeenCalledTimes(1)
})

it('invalidates even batched account A-B-A completions', async () => {
  const finishes: (() => void)[] = []
  vi.mocked(reconcileWidgetGraph).mockImplementation(
    () => new Promise<void>((resolve) => finishes.push(resolve))
  )
  renderHook(() => useWidgetRegistrations('p1', true, [], refresh))
  await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1))
  act(() => {
    useAuthStore.setState({ user: { email: 'b@example.test' } })
    useAuthStore.setState({ user: { email: 'a@example.test' } })
  })
  await act(async () => finishes[0]!())
  expect(refresh).not.toHaveBeenCalled()
  expect(vi.mocked(reconcileWidgetGraph).mock.calls[0]?.[1]?.aborted).toBe(true)
})

it.each([new ApiError(403, 'FORBIDDEN', 'denied'), new Error('offline')])(
  'keeps a failed attempt manual-only through same-account token refresh',
  async (error) => {
    vi.mocked(reconcileWidgetGraph).mockRejectedValueOnce(error)
    const { result } = renderHook(() => useWidgetRegistrations('p1', true, [], refresh))
    const status = error instanceof ApiError ? 'forbidden' : 'error'
    await waitFor(() => expect(result.current.status).toBe(status))
    await act(async () => {
      useAuthStore.setState({ user: { email: 'a@example.test' }, accessToken: 'refreshed' })
    })
    expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1)
    expect(result.current.status).toBe(status)
    act(() => result.current.retry())
    await waitFor(() => expect(reconcileWidgetGraph).toHaveBeenCalledTimes(2))
    expect(refresh).toHaveBeenCalledTimes(1)
  }
)

it('cancels a pending attempt on token refresh and offers manual retry', async () => {
  let finish!: () => void
  vi.mocked(reconcileWidgetGraph).mockReturnValueOnce(
    new Promise<void>((resolve) => {
      finish = resolve
    })
  )
  const { result } = renderHook(() => useWidgetRegistrations('p1', true, [], refresh))
  await waitFor(() => expect(result.current.status).toBe('pending'))
  await act(async () => {
    useAuthStore.setState({ accessToken: 'next-token' })
  })
  expect(vi.mocked(reconcileWidgetGraph).mock.calls[0]?.[1]?.aborted).toBe(true)
  await act(async () => finish())
  expect(refresh).not.toHaveBeenCalled()
  expect(reconcileWidgetGraph).toHaveBeenCalledTimes(1)
  expect(result.current.status).toBe('error')
  act(() => result.current.retry())
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
})
