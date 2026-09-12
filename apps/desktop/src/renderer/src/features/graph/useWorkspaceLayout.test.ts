import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import * as workspace from '../../lib/api/workspace'
import { useWorkspaceLayout } from './useWorkspaceLayout'
import { useAuthStore } from '../../store/authStore'

vi.mock('../../lib/api/workspace', () => ({
  getWorkspaceLayout: vi.fn(),
  saveWorkspaceLayout: vi.fn()
}))

beforeEach(() => {
  vi.clearAllMocks()
  useAuthStore.setState({ accessToken: null, user: null, status: 'unauthenticated' })
  vi.mocked(workspace.getWorkspaceLayout).mockResolvedValue({ version: 0, positions: {} })
  vi.mocked(workspace.saveWorkspaceLayout).mockImplementation(async (_project, body) => ({
    ...body,
    version: body.version + 1
  }))
})

it('persists a drag with the current server version', async () => {
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  await waitFor(() =>
    expect(workspace.saveWorkspaceLayout).toHaveBeenCalledWith(
      'p1',
      {
        version: 0,
        positions: { e1: { x: 10, y: 20 } }
      },
      expect.any(Object)
    )
  )
  await waitFor(() => expect(result.current.status).toBe('ready'))
})

it('serializes moves while a save is in flight without losing newer coordinates', async () => {
  let finish!: (layout: workspace.WorkspaceLayout) => void
  vi.mocked(workspace.saveWorkspaceLayout).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  act(() => result.current.move('e2', { x: 30, y: 40 }))
  await act(async () => finish({ version: 1, positions: { e1: { x: 10, y: 20 } } }))
  await waitFor(() =>
    expect(workspace.saveWorkspaceLayout).toHaveBeenLastCalledWith(
      'p1',
      {
        version: 1,
        positions: { e1: { x: 10, y: 20 }, e2: { x: 30, y: 40 } }
      },
      expect.any(Object)
    )
  )
})

it.each([undefined, ['e1']])(
  'preserves teammate positions on conflict with local graph IDs %j',
  async (ids) => {
    vi.mocked(workspace.saveWorkspaceLayout).mockRejectedValueOnce(
      new ApiError(409, 'conflict', 'Changed')
    )
    const { result } = renderHook(() => useWorkspaceLayout('p1', true, ids))
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(workspace.getWorkspaceLayout).mockResolvedValue({
      version: 2,
      positions: { other: { x: 7, y: 8 } }
    })
    act(() => result.current.move('e1', { x: 10, y: 20 }))
    await waitFor(() => expect(result.current.error).toMatch(/changed elsewhere/i))
    expect(workspace.saveWorkspaceLayout).toHaveBeenCalledTimes(1)
    act(() => result.current.retry())
    await waitFor(() =>
      expect(workspace.saveWorkspaceLayout).toHaveBeenLastCalledWith(
        'p1',
        {
          version: 2,
          positions: { other: { x: 7, y: 8 }, e1: { x: 10, y: 20 } }
        },
        expect.any(Object)
      )
    )
  }
)

it('does not leak positions across a project switch', async () => {
  let finishOldSave!: (layout: workspace.WorkspaceLayout) => void
  let finishNewLoad!: (layout: workspace.WorkspaceLayout) => void
  vi.mocked(workspace.saveWorkspaceLayout).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishOldSave = resolve
      })
  )
  const { result, rerender } = renderHook(({ project }) => useWorkspaceLayout(project, true), {
    initialProps: { project: 'p1' }
  })
  await waitFor(() => expect(result.current.status).toBe('ready'))
  vi.mocked(workspace.getWorkspaceLayout).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishNewLoad = resolve
      })
  )
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  rerender({ project: 'p2' })
  expect(result.current.positions).toEqual({})
  await act(async () => finishOldSave({ version: 1, positions: { e1: { x: 10, y: 20 } } }))
  expect(result.current.positions).toEqual({})
  await act(async () => finishNewLoad({ version: 0, positions: {} }))
  expect(result.current.status).toBe('ready')
  expect(result.current.positions).toEqual({})
})

it('drops a deleted document before the next move and ignores moves for removed entities', async () => {
  const { result, rerender } = renderHook(({ ids }) => useWorkspaceLayout('p1', true, ids), {
    initialProps: { ids: ['doc', 'motor'] }
  })
  await waitFor(() => expect(result.current.status).toBe('ready'))
  await act(async () => result.current.move('doc', { x: 10, y: 20 }))
  rerender({ ids: ['motor'] })
  expect(result.current.positions).not.toHaveProperty('doc')
  await act(async () => result.current.move('motor', { x: 30, y: 40 }))
  expect(workspace.saveWorkspaceLayout).toHaveBeenLastCalledWith(
    'p1',
    {
      version: 1,
      positions: { motor: { x: 30, y: 40 } }
    },
    expect.any(Object)
  )
  act(() => result.current.move('doc', { x: 99, y: 99 }))
  expect(workspace.saveWorkspaceLayout).toHaveBeenCalledTimes(2)
})

it('filters a removed entity out of an in-flight save result and the queued move', async () => {
  let finish!: (layout: workspace.WorkspaceLayout) => void
  vi.mocked(workspace.saveWorkspaceLayout).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const { result, rerender } = renderHook(({ ids }) => useWorkspaceLayout('p1', true, ids), {
    initialProps: { ids: ['doc', 'motor'] }
  })
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('doc', { x: 10, y: 20 }))
  act(() => result.current.move('doc', { x: 20, y: 30 }))
  act(() => result.current.move('motor', { x: 40, y: 50 }))
  rerender({ ids: ['motor'] })
  await act(async () => finish({ version: 1, positions: { doc: { x: 10, y: 20 } } }))
  expect(workspace.saveWorkspaceLayout).toHaveBeenLastCalledWith(
    'p1',
    {
      version: 1,
      positions: { motor: { x: 40, y: 50 } }
    },
    expect.any(Object)
  )
  expect(result.current.positions).toEqual({ motor: { x: 40, y: 50 } })
})

it('ignores a move for an id outside the live set, e.g. a synthetic account anchor', async () => {
  const { result } = renderHook(() => useWorkspaceLayout('p1', true, ['e1']))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('account:c1', { x: 10, y: 20 }))
  expect(workspace.saveWorkspaceLayout).not.toHaveBeenCalled()
  expect(result.current.positions).toEqual({})
  expect(result.current.status).toBe('ready')
})

it('never writes before loading or while offline', () => {
  const { result } = renderHook(() => useWorkspaceLayout('p1', false))
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  expect(workspace.getWorkspaceLayout).not.toHaveBeenCalled()
  expect(workspace.saveWorkspaceLayout).not.toHaveBeenCalled()
})

it('drains a queued move after navigating away from the workspace', async () => {
  let finish!: (layout: workspace.WorkspaceLayout) => void
  vi.mocked(workspace.saveWorkspaceLayout).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const { result, unmount } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  act(() => result.current.move('e2', { x: 30, y: 40 }))
  unmount()
  await act(async () => finish({ version: 1, positions: { e1: { x: 10, y: 20 } } }))
  expect(workspace.saveWorkspaceLayout).toHaveBeenCalledTimes(2)
  expect(vi.mocked(workspace.saveWorkspaceLayout).mock.calls[1]?.[1]).toEqual({
    version: 1,
    positions: { e1: { x: 10, y: 20 }, e2: { x: 30, y: 40 } }
  })
})

it('cancels queued writes if authentication changes after unmount', async () => {
  let finish!: (layout: workspace.WorkspaceLayout) => void
  useAuthStore.setState({ accessToken: 'layout-session-a', user: { email: 'a@example.test' } })
  vi.mocked(workspace.saveWorkspaceLayout).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve
      })
  )
  const { result, unmount } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  act(() => result.current.move('e2', { x: 30, y: 40 }))
  unmount()
  useAuthStore.setState({ accessToken: 'layout-session-b', user: { email: 'b@example.test' } })
  await act(async () => finish({ version: 1, positions: { e1: { x: 10, y: 20 } } }))
  expect(workspace.saveWorkspaceLayout).toHaveBeenCalledTimes(1)
})
