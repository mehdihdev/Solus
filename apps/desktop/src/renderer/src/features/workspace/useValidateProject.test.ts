// The persisted current project is a client-side memory of a server-side row. If
// that row is gone, EVERY project-scoped screen 404s and there is no way back —
// the shell reads the store directly. These cases pin when the memory is
// discarded, and just as importantly when it is NOT.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useValidateProject } from './useValidateProject'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'
import { ApiError } from '../../lib/api/envelope.types'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getProject: vi.fn() }
})

const PROJECT = { id: 'p1', name: 'Rover MK2' }

beforeEach(() => {
  vi.clearAllMocks()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ status: 'authenticated', user: { email: 'a@b.dev' }, onboarded: true })
  useWorkspaceStore.setState({ project: PROJECT, linked: true })
})

describe('useValidateProject', () => {
  it('drops a project the server no longer has', async () => {
    vi.mocked(resources.getProject).mockRejectedValue(new ApiError(404, 'not_found', 'gone'))

    renderHook(() => useValidateProject())

    await waitFor(() => expect(useWorkspaceStore.getState().project).toBeNull())
  })

  it('keeps a project that still resolves', async () => {
    vi.mocked(resources.getProject).mockResolvedValue({ id: 'p1', name: 'Rover MK2' } as never)

    renderHook(() => useValidateProject())

    await waitFor(() => expect(resources.getProject).toHaveBeenCalledWith('p1'))
    expect(useWorkspaceStore.getState().project).toEqual(PROJECT)
  })

  // The important half. "I can't reach the server" is not "your project is
  // gone" — clearing on anything but a 404 would throw away a good reference
  // over a blip, the same mistake as rendering a 401 as "backend unreachable".
  it.each([
    ['401 unauthorized', new ApiError(401, 'unauthorized', 'nope')],
    ['500 server error', new ApiError(500, 'server_error', 'boom')],
    ['network failure', new Error('Failed to fetch')]
  ])('keeps the project on %s', async (_label, error) => {
    vi.mocked(resources.getProject).mockRejectedValue(error)

    renderHook(() => useValidateProject())

    await waitFor(() => expect(resources.getProject).toHaveBeenCalled())
    expect(useWorkspaceStore.getState().project).toEqual(PROJECT)
  })

  it('does nothing when no project is persisted', async () => {
    useWorkspaceStore.setState({ project: null })

    renderHook(() => useValidateProject())

    await waitFor(() => expect(resources.getProject).not.toHaveBeenCalled())
  })

  it('does not check while signed out — an unauthenticated 404 proves nothing', async () => {
    useAuthStore.setState({ status: 'unauthenticated', user: null, onboarded: false })

    renderHook(() => useValidateProject())

    await waitFor(() => expect(resources.getProject).not.toHaveBeenCalled())
  })

  it('checks once, not on every render', async () => {
    vi.mocked(resources.getProject).mockResolvedValue({ id: 'p1', name: 'Rover MK2' } as never)

    const { rerender } = renderHook(() => useValidateProject())
    await waitFor(() => expect(resources.getProject).toHaveBeenCalledTimes(1))
    rerender()
    rerender()

    expect(resources.getProject).toHaveBeenCalledTimes(1)
  })
})
