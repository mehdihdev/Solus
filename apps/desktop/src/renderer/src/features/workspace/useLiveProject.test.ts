// A teammate renamed or archived the open project: the top bar must follow
// (ADR-037). The live hint only says "project:<id> changed"; this hook refetches.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useLiveProject } from './useLiveProject'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import { liveKeys } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getProject: vi.fn() }
})

const PROJECT = { id: 'p1', name: 'Rover MK2', teamId: 't1' }
const detail = (over: Record<string, unknown>): resources.ProjectDetail =>
  ({ id: 'p1', team_id: 't1', name: 'Rover MK2', archived_at: null, ...over }) as never

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
  useWorkspaceStore.setState({ project: PROJECT, linked: true })
})

describe('useLiveProject', () => {
  it('does not fetch until a live hint arrives', async () => {
    renderHook(() => useLiveProject())
    await bumpLive('unrelated')
    expect(resources.getProject).not.toHaveBeenCalled()
  })

  it('updates the active project name on a project-detail bump, keeping its team', async () => {
    vi.mocked(resources.getProject).mockResolvedValue(detail({ name: 'Rover MK3' }))
    renderHook(() => useLiveProject())
    await bumpLive(liveKeys.projectDetail('p1'))
    await waitFor(() => expect(useWorkspaceStore.getState().project?.name).toBe('Rover MK3'))
    expect(useWorkspaceStore.getState().project).toEqual({ ...PROJECT, name: 'Rover MK3' })
  })

  it('does not replace the project object when the name is unchanged', async () => {
    vi.mocked(resources.getProject).mockResolvedValue(detail({}))
    const before = useWorkspaceStore.getState().project
    renderHook(() => useLiveProject())
    await bumpLive(liveKeys.projectDetail('p1'))
    await waitFor(() => expect(resources.getProject).toHaveBeenCalledWith('p1'))
    expect(useWorkspaceStore.getState().project).toBe(before)
  })

  it('closes the project when it was archived', async () => {
    vi.mocked(resources.getProject).mockResolvedValue(detail({ archived_at: '2026-10-03T00:00Z' }))
    renderHook(() => useLiveProject())
    await bumpLive(liveKeys.projectDetail('p1'))
    await waitFor(() => expect(useWorkspaceStore.getState().project).toBeNull())
  })

  it('closes the project when it is gone (404)', async () => {
    vi.mocked(resources.getProject).mockRejectedValue(new ApiError(404, 'not_found', 'gone'))
    renderHook(() => useLiveProject())
    await bumpLive(liveKeys.projectDetail('p1'))
    await waitFor(() => expect(useWorkspaceStore.getState().project).toBeNull())
  })

  it.each([
    ['401', new ApiError(401, 'unauthorized', 'x')],
    ['500', new ApiError(500, 'server_error', 'x')],
    ['network', new Error('Failed to fetch')]
  ])('keeps the project on %s', async (_l, error) => {
    vi.mocked(resources.getProject).mockRejectedValue(error)
    renderHook(() => useLiveProject())
    await bumpLive(liveKeys.projectDetail('p1'))
    await waitFor(() => expect(resources.getProject).toHaveBeenCalled())
    expect(useWorkspaceStore.getState().project).toEqual(PROJECT)
  })

  it('drops a stale answer after the user switched projects', async () => {
    let resolve: (d: resources.ProjectDetail) => void = () => undefined
    vi.mocked(resources.getProject).mockReturnValue(new Promise((r) => (resolve = r)))
    renderHook(() => useLiveProject())
    await bumpLive(liveKeys.projectDetail('p1'))
    useWorkspaceStore.setState({ project: { id: 'p2', name: 'Other' } })
    resolve(detail({ name: 'Late rename' }))
    await new Promise((r) => setTimeout(r, 20))
    expect(useWorkspaceStore.getState().project).toEqual({ id: 'p2', name: 'Other' })
  })

  it('does nothing while signed out', async () => {
    useAuthStore.setState({ status: 'unauthenticated' })
    renderHook(() => useLiveProject())
    await bumpLive(liveKeys.projectDetail('p1'))
    expect(resources.getProject).not.toHaveBeenCalled()
  })
})
