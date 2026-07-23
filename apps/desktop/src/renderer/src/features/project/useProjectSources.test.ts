// Per-project source management (SOLUSDEV-164): list connected sources and act
// on them (sync now, disconnect keeping synced data). Degrades to offline like
// the other workspace hooks (SOLUSDEV-152).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useProjectSources } from './useProjectSources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import * as resources from '../../lib/api/resources'

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
