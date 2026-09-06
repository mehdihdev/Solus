import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import * as resources from '../../lib/api/resources'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useSolusConfig, emptySections, SECTION_LABELS } from './useSolusConfig'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getSolus: vi.fn() }
})

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
})

describe('useSolusConfig', () => {
  it('labels all five sections in order', () => {
    expect(Object.keys(SECTION_LABELS)).toEqual(['hardware', 'details', 'errors', 'docs', 'code'])
    expect(SECTION_LABELS.errors).toBe('Error logging')
    expect(Object.values(emptySections()).every((v) => v.length === 0)).toBe(true)
  })

  it('is offline without a linked project and never fetches', () => {
    const { result } = renderHook(() => useSolusConfig(null))
    expect(result.current.status).toBe('offline')
    expect(vi.mocked(resources.getSolus)).not.toHaveBeenCalled()
  })

  it('loads the sections and refetches on demand', async () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
    vi.mocked(resources.getSolus).mockResolvedValue({
      entity_id: 'solus-1',
      sections: { ...emptySections(), details: [] }
    })
    const { result } = renderHook(() => useSolusConfig('p1'))
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.entityId).toBe('solus-1')
    await act(async () => {
      const again = await result.current.refetch()
      expect(again?.entity_id).toBe('solus-1')
    })
    expect(vi.mocked(resources.getSolus)).toHaveBeenCalledTimes(2)
  })

  it('degrades to offline when the API cannot answer', async () => {
    useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover' } })
    vi.mocked(resources.getSolus).mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useSolusConfig('p1'))
    await waitFor(() => expect(result.current.status).toBe('offline'))
  })
})

it('ignores an old refetch after changing project', async () => {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'First' } })
  vi.mocked(resources.getSolus).mockResolvedValue({ entity_id: 's1', sections: emptySections() })
  const { result, rerender } = renderHook(({ id }) => useSolusConfig(id), {
    initialProps: { id: 'p1' }
  })
  await waitFor(() => expect(result.current.entityId).toBe('s1'))
  let finish!: (value: resources.SolusConfig) => void
  vi.mocked(resources.getSolus).mockReturnValueOnce(
    new Promise((resolve) => {
      finish = resolve
    })
  )
  const pending = result.current.refetch()
  vi.mocked(resources.getSolus).mockResolvedValue({ entity_id: 's2', sections: emptySections() })
  rerender({ id: 'p2' })
  await waitFor(() => expect(result.current.entityId).toBe('s2'))
  await act(async () => {
    finish({ entity_id: 's1', sections: emptySections() })
    await pending
  })
  expect(result.current.entityId).toBe('s2')
})
