// Live summary for the Workspace screen: real counts from getProject
// (whose payload already carries the sources array) plus the full entity list
// via the cursor-following listAllEntities. Failures are classified with
// classifyFetchError so an answering-but-refusing API is never rendered as
// "backend unreachable" — and a failed list never hides honest counts.
import { it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useWorkspaceGraph, clearWorkspaceGraphCache } from './useWorkspaceGraph'
import { GRAPH_CACHE_TTL_MS } from './graphCache'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { ApiError } from '../../lib/api/envelope.types'
import * as resources from '../../lib/api/resources'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return {
    ...actual,
    getProject: vi.fn(),
    listAllEntities: vi.fn(),
    listAllSources: vi.fn().mockResolvedValue([])
  }
})

vi.mock('../../lib/api/workspace', () => ({ listAllRelations: vi.fn().mockResolvedValue([]) }))

const DETAIL: resources.ProjectDetail = {
  id: 'p1',
  team_id: 't1',
  name: 'Rover MK2',
  description: null,
  archived_at: null,
  created_at: '',
  updated_at: '',
  stats: { entities: 12, relations: 30 },
  sources: [{ id: 's1' }]
}

const ENTITY: resources.Entity = {
  id: 'e1',
  type: 'part',
  domain: 'mechanical',
  name: 'elbow motor',
  source_key: 'onshape:e1'
}

function linkProject(): void {
  useWorkspaceStore.setState({ linked: true, project: { id: 'p1', name: 'Rover MK2' } })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  clearWorkspaceGraphCache()
  useWorkspaceStore.getState().reset()
})

it('reports offline when the workspace is not linked (dev bypass)', () => {
  const { result } = renderHook(() => useWorkspaceGraph())
  expect(result.current.status).toBe('offline')
  expect(vi.mocked(resources.getProject)).not.toHaveBeenCalled()
})

it('reports offline when linked but no project is selected', () => {
  useWorkspaceStore.setState({ linked: true, project: null })
  const { result } = renderHook(() => useWorkspaceGraph())
  expect(result.current.status).toBe('offline')
})

it('loads counts from the project detail and the full entity list', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
  const { result } = renderHook(() => useWorkspaceGraph())
  expect(result.current.status).toBe('loading')
  await waitFor(() => expect(result.current.status).toBe('ready'))
  expect(result.current.entityCount).toBe(12)
  expect(result.current.relationCount).toBe(30)
  expect(result.current.sourceCount).toBe(1)
  expect(result.current.entities).toEqual([ENTITY])
  expect(vi.mocked(resources.getProject)).toHaveBeenCalledWith('p1', expect.anything())
  expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledWith('p1', expect.anything())
})

it('degrades to offline when the API is unreachable', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockRejectedValue(new Error('unreachable'))
  vi.mocked(resources.listAllEntities).mockRejectedValue(new Error('unreachable'))
  const { result } = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(result.current.status).toBe('offline'))
  expect(result.current.entityCount).toBe(0)
})

it('reports error — not offline — when the API answers with a refusal', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockRejectedValue(new ApiError(403, 'forbidden', 'nope'))
  vi.mocked(resources.listAllEntities).mockResolvedValue([])
  const { result } = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(result.current.status).toBe('error'))
})

it('keeps honest counts with a null entity list when only the list call fails', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockRejectedValue(new Error('boom'))
  const { result } = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(result.current.status).toBe('ready'))
  expect(result.current.entityCount).toBe(12)
  expect(result.current.entities).toBeNull()
})

// SOLUSDEV-234: the Graph screen mounts on every visit, and each mount used
// to re-walk every entity page. The detail (one request) now validates a
// retained list; the walk repeats only when the graph changed or the entry
// is stale.
it('serves the retained list on remount and skips the page walk when unchanged', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()

  const second = renderHook(() => useWorkspaceGraph())
  // No loading flash: the retained list renders before the detail answers.
  expect(second.result.current.status).toBe('ready')
  expect(second.result.current.entities).toEqual([ENTITY])
  await waitFor(() => expect(vi.mocked(resources.getProject)).toHaveBeenCalledTimes(2))
  expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledTimes(1)
})

it('re-walks the pages when the detail says the graph changed', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()

  const grown = { ...DETAIL, stats: { entities: 13, relations: 30 } }
  const added = { ...ENTITY, id: 'e2' }
  vi.mocked(resources.getProject).mockResolvedValue(grown)
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY, added])
  const second = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(second.result.current.entityCount).toBe(13))
  expect(second.result.current.entities).toEqual([ENTITY, added])
  expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledTimes(2)
})

it('re-walks the pages once the entry is older than the TTL', async () => {
  vi.useFakeTimers({ toFake: ['Date'] })
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()

  vi.setSystemTime(Date.now() + GRAPH_CACHE_TTL_MS + 1)
  renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledTimes(2))
})

it("never serves one project's list to another", async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()

  useWorkspaceStore.setState({ linked: true, project: { id: 'p2', name: 'Other' } })
  vi.mocked(resources.getProject).mockResolvedValue({ ...DETAIL, id: 'p2' })
  vi.mocked(resources.listAllEntities).mockResolvedValue([])
  const second = renderHook(() => useWorkspaceGraph())
  expect(second.result.current.status).toBe('loading')
  expect(second.result.current.entities).toBeNull()
  await waitFor(() => expect(second.result.current.status).toBe('ready'))
  expect(vi.mocked(resources.listAllEntities)).toHaveBeenLastCalledWith('p2', expect.anything())
})

it('does not retain a failed list', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockRejectedValue(new Error('boom'))
  const first = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(first.result.current.status).toBe('ready'))
  first.unmount()

  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
  const second = renderHook(() => useWorkspaceGraph())
  await waitFor(() => expect(second.result.current.entities).toEqual([ENTITY]))
  expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledTimes(2)
})

// SOLUSDEV-250 P6: a revision bump (local onGraphChanged or SSE graph.changed)
// runs the cheap detail read; the pages are walked only when the version moved.
it('validates a reconnect against the retained snapshot and walks only on a changed version', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
  const view = renderHook(({ revision }) => useWorkspaceGraph(0, revision), {
    initialProps: { revision: 0 }
  })
  await waitFor(() => expect(view.result.current.status).toBe('ready'))
  expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledTimes(1)

  view.rerender({ revision: 1 })
  await waitFor(() => expect(vi.mocked(resources.getProject)).toHaveBeenCalledTimes(2))
  expect(view.result.current.entities).toEqual([ENTITY])
  expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledTimes(1)

  const added = { ...ENTITY, id: 'e2' }
  vi.mocked(resources.getProject).mockResolvedValue({
    ...DETAIL,
    graph_updated_at: '2026-09-07T00:00:01Z'
  })
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY, added])
  view.rerender({ revision: 2 })
  await waitFor(() => expect(view.result.current.entities).toEqual([ENTITY, added]))
  expect(vi.mocked(resources.listAllEntities)).toHaveBeenCalledTimes(2)
})

it('refreshes graph event revisions even when timestamp and counts are unchanged', async () => {
  linkProject()
  vi.mocked(resources.getProject).mockResolvedValue(DETAIL)
  vi.mocked(resources.listAllEntities).mockResolvedValue([ENTITY])
  const { result, rerender } = renderHook(({ revision }) => useWorkspaceGraph(revision), {
    initialProps: { revision: 0 }
  })
  await waitFor(() => expect(result.current.entities).toEqual([ENTITY]))
  const changed = { ...ENTITY, name: 'committed later with older timestamp' }
  vi.mocked(resources.listAllEntities).mockResolvedValue([changed])
  rerender({ revision: 1 })
  await waitFor(() => expect(result.current.entities).toEqual([changed]))
})
