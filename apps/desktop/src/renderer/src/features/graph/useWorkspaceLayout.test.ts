import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../lib/api/envelope.types'
import * as workspace from '../../lib/api/workspace'
import { useWorkspaceLayout } from './useWorkspaceLayout'
import { useAuthStore } from '../../store/authStore'
import { liveKeys, resetLiveRevisions, useLiveRevisionStore } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'

vi.mock('../../lib/api/workspace', () => ({
  getWorkspaceLayout: vi.fn(),
  saveWorkspaceLayout: vi.fn()
}))

beforeEach(() => {
  vi.clearAllMocks()
  resetLiveRevisions()
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

async function layoutChanged(projectId: string, version: number): Promise<void> {
  useLiveRevisionStore.getState().recordLayoutVersion(projectId, version)
  await bumpLive(liveKeys.projectLayout(projectId))
}

it('reloads silently on a newer layout.changed when nothing is pending', async () => {
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  vi.mocked(workspace.getWorkspaceLayout).mockResolvedValue({
    version: 3,
    positions: { mate: { x: 1, y: 2 } }
  })
  const seen: string[] = []
  const poll = setInterval(() => seen.push(result.current.status), 5)
  await layoutChanged('p1', 3)
  clearInterval(poll)
  await waitFor(() => expect(result.current.positions).toEqual({ mate: { x: 1, y: 2 } }))
  expect(seen.every((status) => status === 'ready')).toBe(true)
  // The reload moved the version: the next save carries it and does not 409.
  act(() => result.current.move('e1', { x: 5, y: 6 }))
  await waitFor(() =>
    expect(workspace.saveWorkspaceLayout).toHaveBeenLastCalledWith(
      'p1',
      { version: 3, positions: { mate: { x: 1, y: 2 }, e1: { x: 5, y: 6 } } },
      expect.any(Object)
    )
  )
})

it('does not refetch for a version that is not newer than the loaded one', async () => {
  vi.mocked(workspace.getWorkspaceLayout).mockResolvedValue({ version: 4, positions: {} })
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  await layoutChanged('p1', 4)
  await layoutChanged('p1', 2)
  expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(1)
})

it('ignores a layout hint for another project', async () => {
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  await layoutChanged('p2', 9)
  expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(1)
})

it('echo of our own save does not trigger a reload', async () => {
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  await waitFor(() => expect(workspace.saveWorkspaceLayout).toHaveBeenCalledTimes(1))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  await layoutChanged('p1', 1)
  expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(1)
})

it('with unsaved moves, refetches the latest but keeps the moves so the next save does not 409', async () => {
  vi.mocked(workspace.saveWorkspaceLayout).mockRejectedValueOnce(new Error('offline blip'))
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  await waitFor(() => expect(result.current.status).toBe('error'))
  vi.mocked(workspace.getWorkspaceLayout).mockResolvedValue({
    version: 3,
    positions: { mate: { x: 7, y: 8 } }
  })
  await layoutChanged('p1', 3)
  await waitFor(() => expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(2))
  await waitFor(() =>
    expect(result.current.positions).toEqual({ mate: { x: 7, y: 8 }, e1: { x: 10, y: 20 } })
  )
  act(() => result.current.retry())
  await waitFor(() =>
    expect(workspace.saveWorkspaceLayout).toHaveBeenLastCalledWith(
      'p1',
      { version: 3, positions: { mate: { x: 7, y: 8 }, e1: { x: 10, y: 20 } } },
      expect.any(Object)
    )
  )
})

it('defers a hint that arrives mid-save and reloads after the save if a teammate is ahead', async () => {
  let finish!: (layout: workspace.WorkspaceLayout) => void
  vi.mocked(workspace.saveWorkspaceLayout).mockImplementationOnce(
    () => new Promise((resolve) => (finish = resolve))
  )
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  act(() => result.current.move('e1', { x: 10, y: 20 }))
  await layoutChanged('p1', 4)
  expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(1)
  vi.mocked(workspace.getWorkspaceLayout).mockResolvedValue({
    version: 4,
    positions: { e1: { x: 10, y: 20 }, mate: { x: 3, y: 3 } }
  })
  await act(async () => finish({ version: 1, positions: { e1: { x: 10, y: 20 } } }))
  await waitFor(() => expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(result.current.positions.mate).toEqual({ x: 3, y: 3 }))
})

it('applies a hint that arrived before the first load finished', async () => {
  let finishLoad!: (layout: workspace.WorkspaceLayout) => void
  vi.mocked(workspace.getWorkspaceLayout).mockImplementationOnce(
    () => new Promise((resolve) => (finishLoad = resolve))
  )
  renderHook(() => useWorkspaceLayout('p1', true))
  await layoutChanged('p1', 5)
  vi.mocked(workspace.getWorkspaceLayout).mockResolvedValue({ version: 5, positions: {} })
  await act(async () => finishLoad({ version: 2, positions: {} }))
  await waitFor(() => expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(2))
})

it('serializes overlapping reloads and ends on the newest layout', async () => {
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  let late!: (layout: workspace.WorkspaceLayout) => void
  vi.mocked(workspace.getWorkspaceLayout).mockImplementationOnce(
    () => new Promise((resolve) => (late = resolve))
  )
  await layoutChanged('p1', 2)
  vi.mocked(workspace.getWorkspaceLayout).mockResolvedValue({
    version: 3,
    positions: { newest: { x: 1, y: 1 } }
  })
  await layoutChanged('p1', 3)
  expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(2)
  await act(async () => late({ version: 2, positions: { stale: { x: 9, y: 9 } } }))
  await waitFor(() => expect(workspace.getWorkspaceLayout).toHaveBeenCalledTimes(3))
  await waitFor(() => expect(result.current.positions).toEqual({ newest: { x: 1, y: 1 } }))
})

it('a failed live reload keeps the current positions and status', async () => {
  const { result } = renderHook(() => useWorkspaceLayout('p1', true))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  vi.mocked(workspace.getWorkspaceLayout).mockRejectedValue(new Error('blip'))
  await layoutChanged('p1', 3)
  expect(result.current.status).toBe('ready')
  expect(result.current.error).toBeNull()
})
