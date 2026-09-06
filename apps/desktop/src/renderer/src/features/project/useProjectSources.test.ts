// Per-project source management (SOLUSDEV-164): list connected sources and act
// on them (sync now, disconnect keeping synced data). Degrades to offline like
// the other workspace hooks (SOLUSDEV-152).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useProjectSources, SOURCES_POLL_MS } from './useProjectSources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'
import { useInterval } from '../../lib/useInterval'

vi.mock('../../lib/useInterval', () => ({ useInterval: vi.fn() }))

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    listSources: vi.fn(),
    triggerSync: vi.fn(),
    disconnectSource: vi.fn()
  }
})

const SOURCE = {
  id: 's1',
  name: 'octo/arm',
  type: 'github',
  status: 'connected'
} as resources.Source

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
})

describe('useProjectSources', () => {
  it('reports offline when no project is selected', () => {
    useWorkspaceStore.setState({ project: null })
    const { result } = renderHook(() => useProjectSources())
    expect(result.current.status).toBe('offline')
    expect(vi.mocked(resources.listSources)).not.toHaveBeenCalled()
  })

  it('lists the project sources', async () => {
    vi.mocked(resources.listSources).mockResolvedValue([SOURCE])
    const { result } = renderHook(() => useProjectSources())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.sources).toEqual([SOURCE])
    expect(vi.mocked(resources.listSources)).toHaveBeenCalledWith('p1')
  })

  it('syncs a source then refreshes the list', async () => {
    vi.mocked(resources.listSources).mockResolvedValue([SOURCE])
    vi.mocked(resources.triggerSync).mockResolvedValue({ job_id: 'j1', status: 'queued' })
    const { result } = renderHook(() => useProjectSources())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await act(async () => {
      await result.current.actions.syncNow('s1')
    })
    expect(vi.mocked(resources.triggerSync)).toHaveBeenCalledWith('p1', 's1')
    expect(vi.mocked(resources.listSources)).toHaveBeenCalledTimes(2)
  })

  it('disconnects a source retaining synced data, then refreshes', async () => {
    vi.mocked(resources.listSources).mockResolvedValue([SOURCE])
    vi.mocked(resources.disconnectSource).mockResolvedValue({ id: 's1', retained_entities: true })
    const { result } = renderHook(() => useProjectSources())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let ok = false
    await act(async () => {
      ok = await result.current.actions.disconnect('s1')
    })
    expect(ok).toBe(true)
    expect(vi.mocked(resources.disconnectSource)).toHaveBeenCalledWith('p1', 's1', {
      retainEntities: true
    })
    expect(vi.mocked(resources.listSources)).toHaveBeenCalledTimes(2)
  })

  it('reports a failed disconnect without throwing', async () => {
    vi.mocked(resources.listSources).mockResolvedValue([SOURCE])
    vi.mocked(resources.disconnectSource).mockRejectedValue(new Error('forbidden'))
    const { result } = renderHook(() => useProjectSources())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    let ok = true
    await act(async () => {
      ok = await result.current.actions.disconnect('s1')
    })
    expect(ok).toBe(false)
  })
})

describe('useProjectSources — live refresh', () => {
  it('re-reads the list on a timer so status and counts stay current', async () => {
    vi.mocked(resources.listSources).mockResolvedValue([SOURCE])

    renderHook(() => useProjectSources())
    await waitFor(() => expect(resources.listSources).toHaveBeenCalled())

    // The page refreshes itself rather than waiting for a click. This polls OUR
    // api only — the connector never talks to the provider on this timer.
    const [, ms, enabled] = vi.mocked(useInterval).mock.calls.at(-1)!
    expect(ms).toBe(SOURCES_POLL_MS)
    expect(enabled).toBe(true)
  })

  it('is not polling when there is no project to poll for', async () => {
    useWorkspaceStore.setState({ project: null })

    renderHook(() => useProjectSources())

    await waitFor(() => expect(vi.mocked(useInterval).mock.calls.length).toBeGreaterThan(0))
    expect(vi.mocked(useInterval).mock.calls.at(-1)![2]).toBe(false)
  })

  it('keeps the list on screen when a refresh fails', async () => {
    // On a 10s timer one blip must not blank the page and restore it a moment
    // later; only an empty list may report offline.
    vi.mocked(resources.listSources).mockResolvedValue([SOURCE])
    const { result } = renderHook(() => useProjectSources())
    await waitFor(() => expect(result.current.status).toBe('ready'))

    vi.mocked(resources.listSources).mockRejectedValueOnce(new Error('blip'))
    await act(async () => {
      await result.current.actions.refresh()
    })

    expect(result.current.sources).toHaveLength(1)
    expect(result.current.status).toBe('ready')
  })
})

describe('useProjectSources — project switch mid-flight (SOLUSDEV-242)', () => {
  it('drops a response for a project the user has since left', async () => {
    let resolveA: (sources: resources.Source[]) => void = () => undefined
    vi.mocked(resources.listSources).mockImplementationOnce(
      () => new Promise<resources.Source[]>((resolve) => (resolveA = resolve))
    )
    const { result, rerender } = renderHook(() => useProjectSources())
    // Switch to project B while A's list is still in flight; B answers empty.
    vi.mocked(resources.listSources).mockResolvedValueOnce([])
    act(() => {
      useWorkspaceStore.setState({ project: { id: 'p2', name: 'Arm' } })
    })
    rerender()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    // A's documents land late — they must not be painted over B's.
    await act(async () => {
      resolveA([SOURCE])
      await Promise.resolve()
    })
    expect(result.current.sources).toEqual([])
  })
})
