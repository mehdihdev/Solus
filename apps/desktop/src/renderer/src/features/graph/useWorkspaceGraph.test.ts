import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'
import * as workspace from '../../lib/api/workspace'
import {
  clearWorkspaceGraphCache,
  forgetWorkspaceGraph,
  useWorkspaceGraph
} from './useWorkspaceGraph'

vi.mock('../../lib/api/resources', async (original) => ({
  ...(await original<typeof resources>()),
  getProject: vi.fn(),
  listAllEntities: vi.fn(),
  listAllSources: vi.fn()
}))
vi.mock('../../lib/api/workspace', () => ({ listAllRelations: vi.fn() }))

beforeEach(() => {
  useAuthStore.setState({
    status: 'authenticated',
    user: { email: 'a@example.invalid' },
    accessToken: 'qa-a'
  })
  clearWorkspaceGraphCache()
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Robot' } })
  vi.mocked(resources.getProject).mockResolvedValue({
    id: 'p1',
    team_id: 't',
    name: 'Robot',
    description: null,
    archived_at: null,
    created_at: '',
    updated_at: '',
    sources: [],
    stats: { entities: 1, relations: 0 }
  })
  vi.mocked(resources.listAllEntities).mockResolvedValue([
    { id: 'e', type: 'part', domain: 'mechanical', name: 'Part', source_key: '' }
  ])
  vi.mocked(workspace.listAllRelations).mockResolvedValue([])
  vi.mocked(resources.listAllSources).mockResolvedValue([])
})

it('carries the project sources on the snapshot and retains them (SOLUSDEV-250 P5)', async () => {
  const source = { id: 's1', project_id: 'p1', type: 'github' } as resources.Source
  vi.mocked(resources.listAllSources).mockResolvedValue([source])
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  expect(first.result.current.sources).toEqual([source])
  expect(resources.listAllSources).toHaveBeenCalledWith('p1', expect.anything())
  first.unmount()
  const second = renderHook(() => useWorkspaceGraph())
  expect(second.result.current.sources).toEqual([source])
})

it('stays ready with no sources when the source listing fails', async () => {
  vi.mocked(resources.listAllSources).mockRejectedValue(new Error('boom'))
  const { result } = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(result.current.status).toBe('ready'))
  expect(result.current.sources).toEqual([])
  expect(result.current.entities).toHaveLength(1)
  expect(result.current.errorMessage).toBeNull()
})

it('clears mounted and retained graphs when the signed-in account changes', async () => {
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.entities).toHaveLength(1))
  vi.mocked(resources.getProject).mockReturnValue(new Promise(() => undefined))
  act(() => useAuthStore.setState({ user: { email: 'b@example.invalid' }, accessToken: 'qa-b' }))
  expect(first.result.current.entities).toBeNull()
  first.unmount()
  const second = renderHook(() => useWorkspaceGraph())
  expect(second.result.current.entities).toBeNull()
})

it('does not let a previous account response repopulate the retained graph', async () => {
  let resolve!: (entities: resources.Entity[]) => void
  vi.mocked(resources.listAllEntities).mockReturnValue(
    new Promise((done) => {
      resolve = done
    })
  )
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(resources.listAllEntities).toHaveBeenCalledOnce())
  vi.mocked(resources.getProject).mockReturnValue(new Promise(() => undefined))
  act(() => useAuthStore.setState({ user: { email: 'b@example.invalid' }, accessToken: 'qa-b' }))
  await act(async () =>
    resolve([
      { id: 'private-a', type: 'part', domain: 'mechanical', name: 'Private A', source_key: '' }
    ])
  )
  expect(first.result.current.entities).toBeNull()
  first.unmount()
  const second = renderHook(() => useWorkspaceGraph())
  expect(second.result.current.entities).toBeNull()
})

it('retains complete graph snapshots across screen visits and validates only project detail', async () => {
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()
  const second = renderHook(() => useWorkspaceGraph())
  expect(second.result.current.entities).toHaveLength(1)
  await waitFor(() => expect(resources.getProject).toHaveBeenCalledTimes(2))
  expect(resources.listAllEntities).toHaveBeenCalledTimes(1)
  expect(workspace.listAllRelations).toHaveBeenCalledTimes(1)
})

it('forgets a single retained snapshot so the next visit re-walks that graph (SOLUSDEV-242)', async () => {
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()
  forgetWorkspaceGraph('p1')
  const second = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(second.result.current.status).toBe('ready'))
  expect(resources.listAllEntities).toHaveBeenCalledTimes(2)
})

it('refreshes cached entities and relations when project counts change', async () => {
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()
  const detail = await resources.getProject('p1')
  vi.mocked(resources.getProject).mockResolvedValue({
    ...detail,
    stats: { entities: 2, relations: 1 }
  })
  const second = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(second.result.current.entityCount).toBe(2))
  expect(resources.listAllEntities).toHaveBeenCalledTimes(2)
  expect(workspace.listAllRelations).toHaveBeenCalledTimes(2)
})

it('loads a teammate rename on screen return with equal counts and source stamps', async () => {
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()
  const detail = await resources.getProject('p1')
  vi.mocked(resources.getProject).mockResolvedValue({ ...detail, graph_updated_at: 'later' })
  vi.mocked(resources.listAllEntities).mockResolvedValue([
    { id: 'e', type: 'physical_robot', domain: 'project', name: 'Leader', source_key: '' }
  ])
  const second = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(second.result.current.entities?.[0]?.name).toBe('Leader'))
  expect(resources.listAllEntities).toHaveBeenCalledTimes(2)
})

it('loads graph entities and links together without syncing a source', async () => {
  const { result } = renderHook(() => useWorkspaceGraph(0))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  expect(result.current.entities).toHaveLength(1)
  expect(result.current.relations).toEqual([])
  expect(workspace.listAllRelations).toHaveBeenCalledWith('p1', expect.anything())
})

it('does not expose the old project while a different project loads', async () => {
  const { result } = renderHook(() => useWorkspaceGraph(0))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  vi.mocked(resources.getProject).mockReturnValue(new Promise(() => undefined))
  act(() => useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } }))
  expect(result.current.entities).toBeNull()
  expect(result.current.status).toBe('loading')
})

it('reports missing links instead of showing all children as unrelated roots', async () => {
  vi.mocked(workspace.listAllRelations).mockRejectedValue(new Error('No links'))
  const { result } = renderHook(() => useWorkspaceGraph(0))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  expect(result.current.entities).toBeNull()
  expect(result.current.errorMessage).toMatch(/links/i)
})

it('keeps the visible graph mounted while a mutation refresh is in flight', async () => {
  const { result, rerender } = renderHook(({ revision }) => useWorkspaceGraph(revision), {
    initialProps: { revision: 0 }
  })
  await waitFor(() => expect(result.current.status).toBe('ready'))
  vi.mocked(resources.getProject).mockReturnValue(new Promise(() => undefined))
  rerender({ revision: 1 })
  expect(result.current.status).toBe('ready')
  expect(result.current.entities).toHaveLength(1)
})

it('validates on first stream readiness without rewalking an unchanged graph', async () => {
  const view = renderHook(({ revision, validation }) => useWorkspaceGraph(revision, validation), {
    initialProps: { revision: 1, validation: 0 }
  })
  await waitFor(() => expect(view.result.current.status).toBe('ready'))
  view.rerender({ revision: 1, validation: 1 })
  await waitFor(() => expect(resources.getProject).toHaveBeenCalledTimes(2))
  expect(resources.listAllEntities).toHaveBeenCalledTimes(1)
  const detail = await resources.getProject('p1')
  vi.mocked(resources.getProject).mockResolvedValue({
    ...detail,
    stats: { entities: 2, relations: 0 }
  })
  view.rerender({ revision: 1, validation: 2 })
  await waitFor(() => expect(view.result.current.entityCount).toBe(2))
  expect(resources.listAllEntities).toHaveBeenCalledTimes(2)
})

it('isolates refresh transports and prevents an obsolete response overwriting the retained graph', async () => {
  let release!: (entities: resources.Entity[]) => void
  vi.mocked(resources.listAllEntities).mockReturnValueOnce(
    new Promise((resolve) => {
      release = resolve
    })
  )
  const view = renderHook(({ revision }) => useWorkspaceGraph(revision), {
    initialProps: { revision: 0 }
  })
  await waitFor(() => expect(resources.listAllEntities).toHaveBeenCalledOnce())
  view.rerender({ revision: 1 })
  await waitFor(() => expect(view.result.current.entities?.[0]?.id).toBe('e'))
  expect(vi.mocked(resources.listAllEntities).mock.calls[0]?.[1]).not.toBe(
    vi.mocked(resources.listAllEntities).mock.calls[1]?.[1]
  )
  await act(async () =>
    release([{ id: 'obsolete', type: 'part', domain: 'mechanical', name: 'Old', source_key: '' }])
  )
  view.unmount()
  const reopened = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(reopened.result.current.entities?.[0]?.id).toBe('e'))
})
