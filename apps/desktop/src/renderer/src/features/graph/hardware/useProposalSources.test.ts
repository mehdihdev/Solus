import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { notifyProposalSourcesChanged, useProposalSources } from './useProposalSources'
import { useAuthStore } from '../../../store/authStore'

const original = window.solus
const sourceRef = '00000000-0000-0000-0000-000000000001'
function install(list: ReturnType<typeof vi.fn>): void {
  Object.defineProperty(window, 'solus', {
    configurable: true,
    value: { hardware: { sources: { list } } }
  })
}
afterEach(() => Object.defineProperty(window, 'solus', { configurable: true, value: original }))

it('supplies only opaque refs and reloads when a selected source changes', async () => {
  const list = vi.fn().mockResolvedValue({
    ok: true,
    value: {
      projectId: 'p1',
      accountId: 'a1',
      sources: [{ sourceRef, contentSha256: 'a'.repeat(64), displayName: 'motor.py' }]
    }
  })
  install(list)
  const { result } = renderHook(() => useProposalSources('p1'))
  await waitFor(() => expect(result.current.refs).toEqual([`source:${sourceRef}`]))
  const first = result.current.key
  list.mockResolvedValue({ ok: true, value: { projectId: 'p1', accountId: 'a1', sources: [] } })
  act(() => notifyProposalSourcesChanged())
  await waitFor(() => expect(result.current.refs).toEqual([]))
  expect(result.current.key).not.toBe(first)
})

it('rejects a list from another project without silently using wire-only review', async () => {
  install(
    vi
      .fn()
      .mockResolvedValue({ ok: true, value: { projectId: 'other', accountId: 'a1', sources: [] } })
  )
  const { result } = renderHook(() => useProposalSources('p1'))
  await waitFor(() => expect(result.current.error).toBeTruthy())
  expect(result.current.refs).toBeNull()
})

it('drops a pending list after a scope change', async () => {
  let resolve!: (result: unknown) => void
  const list = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done
        })
    )
    .mockResolvedValue({ ok: true, value: { projectId: 'p2', accountId: 'a2', sources: [] } })
  install(list)
  const { result, rerender } = renderHook(({ project }) => useProposalSources(project), {
    initialProps: { project: 'p1' }
  })
  rerender({ project: 'p2' })
  await waitFor(() => expect(result.current.refs).toEqual([]))
  act(() =>
    resolve({ ok: true, value: { projectId: 'p1', accountId: 'a1', sources: [{ sourceRef }] } })
  )
  expect(result.current.refs).toEqual([])
})

it('shares a settled native snapshot with a newly mounted consumer without reloading', async () => {
  const list = vi.fn().mockResolvedValue({
    ok: true,
    value: { projectId: 'p1', accountId: 'a1', sources: [] }
  })
  install(list)
  const first = renderHook(() => useProposalSources('p1'))
  await waitFor(() => expect(first.result.current.refs).toEqual([]))
  const second = renderHook(() => useProposalSources('p1'))
  expect(second.result.current).toBe(first.result.current)
  expect(list).toHaveBeenCalledTimes(1)
})

it('deduplicates pending native loads and invalidates every consumer together', async () => {
  let resolve!: (value: unknown) => void
  const list = vi.fn().mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done
      })
  )
  install(list)
  const first = renderHook(() => useProposalSources('p1'))
  const second = renderHook(() => useProposalSources('p1'))
  await waitFor(() => expect(list).toHaveBeenCalledTimes(1))
  await act(async () =>
    resolve({ ok: true, value: { projectId: 'p1', accountId: 'a1', sources: [] } })
  )
  expect(second.result.current).toBe(first.result.current)
  act(() => notifyProposalSourcesChanged())
  await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
  expect(first.result.current.refs).toBeNull()
  expect(second.result.current).toBe(first.result.current)
})

it('discards old results on token changes and shares the new authority with later mounts', async () => {
  const oldToken = useAuthStore.getState().accessToken
  const pending: ((value: unknown) => void)[] = []
  const list = vi.fn().mockImplementation(() => new Promise((resolve) => pending.push(resolve)))
  install(list)
  const first = renderHook(() => useProposalSources('p1'))
  await waitFor(() => expect(list).toHaveBeenCalledTimes(1))
  act(() => useAuthStore.setState({ accessToken: 'different-test-session' }))
  await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
  const second = renderHook(() => useProposalSources('p1'))
  await act(async () =>
    pending[0]({
      ok: true,
      value: { projectId: 'p1', accountId: 'old', sources: [{ sourceRef, contentSha256: 'a' }] }
    })
  )
  expect(first.result.current.refs).toBeNull()
  expect(second.result.current).toBe(first.result.current)
  await act(async () =>
    pending[1]({ ok: true, value: { projectId: 'p1', accountId: 'new', sources: [] } })
  )
  expect(first.result.current.refs).toEqual([])
  expect(second.result.current).toBe(first.result.current)
  first.unmount()
  second.unmount()
  act(() => useAuthStore.setState({ accessToken: oldToken }))
})
