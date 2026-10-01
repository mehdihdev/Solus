// Identity hook: real profile when linked, auth-email fallback when offline.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useMe, displayName } from './useMe'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useAuthStore } from '../../store/authStore'
import * as resources from '../../lib/api/resources'
import { liveKeys, resetLiveRevisions } from '../../store/liveRevisionStore'
import { bumpLive } from '../live/testBump'

vi.mock('../../lib/api/resources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/api/resources')>()
  return { ...actual, getMe: vi.fn() }
})

const ME: resources.Me = {
  id: 'u1',
  email: 'maya@strider.dev',
  name: 'Maya Krishnan',
  avatar_url: null,
  created_at: '2026-07-01T00:00:00Z',
  teams: []
}

beforeEach(() => {
  vi.clearAllMocks()
  resetLiveRevisions()
  useWorkspaceStore.getState().reset()
  useAuthStore.setState({ user: { email: 'fallback@solus.local' }, status: 'authenticated' })
})

describe('displayName', () => {
  it('prefers the profile name', () => {
    expect(displayName('Maya Krishnan', 'maya@strider.dev')).toBe('Maya Krishnan')
  })
  it('humanizes the email local part when no name', () => {
    expect(displayName(null, 'maya.k@strider.dev')).toBe('maya k')
  })
  it('falls back to "You" with no name or email', () => {
    expect(displayName(null, '')).toBe('You')
  })
})

describe('useMe', () => {
  it('loads the real profile when the workspace is linked', async () => {
    useWorkspaceStore.setState({ linked: true })
    vi.mocked(resources.getMe).mockResolvedValue(ME)
    const { result } = renderHook(() => useMe())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.name).toBe('Maya Krishnan')
    expect(result.current.email).toBe('maya@strider.dev')
  })

  it('loads the real profile when authenticated even if not linked', async () => {
    // A signed-in user who skipped onboarding must still get their real name,
    // not the email-local-part fallback (SOLUSDEV-152).
    useWorkspaceStore.setState({ linked: false })
    useAuthStore.setState({ user: { email: 'maya@strider.dev' }, status: 'authenticated' })
    vi.mocked(resources.getMe).mockResolvedValue(ME)
    const { result } = renderHook(() => useMe())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.name).toBe('Maya Krishnan')
    expect(resources.getMe).toHaveBeenCalled()
  })

  it('is offline with the auth email when neither authenticated nor linked', async () => {
    useAuthStore.setState({ user: { email: 'fallback@solus.local' }, status: 'unauthenticated' })
    const { result } = renderHook(() => useMe())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.email).toBe('fallback@solus.local')
    expect(resources.getMe).not.toHaveBeenCalled()
  })

  it('falls back to offline when the profile fetch fails', async () => {
    useWorkspaceStore.setState({ linked: true })
    vi.mocked(resources.getMe).mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useMe())
    await waitFor(() => expect(result.current.status).toBe('offline'))
    expect(result.current.email).toBe('fallback@solus.local')
  })
})

describe('useMe — live refresh (ADR-037)', () => {
  it('refetches the profile when the me revision bumps, without flashing loading', async () => {
    useWorkspaceStore.setState({ linked: true })
    vi.mocked(resources.getMe).mockResolvedValue(ME)
    const { result } = renderHook(() => useMe())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    vi.mocked(resources.getMe).mockResolvedValue({ ...ME, name: 'Maya K.' })
    await bumpLive(liveKeys.me)
    await waitFor(() => expect(result.current.name).toBe('Maya K.'))
    expect(resources.getMe).toHaveBeenCalledTimes(2)
    expect(result.current.status).toBe('ready')
  })

  it('ignores bumps for other keys', async () => {
    useWorkspaceStore.setState({ linked: true })
    vi.mocked(resources.getMe).mockResolvedValue(ME)
    const { result } = renderHook(() => useMe())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await bumpLive(liveKeys.notifications, liveKeys.team('t1'))
    expect(resources.getMe).toHaveBeenCalledTimes(1)
  })

  it('keeps the loaded profile when a live refresh fails', async () => {
    useWorkspaceStore.setState({ linked: true })
    vi.mocked(resources.getMe).mockResolvedValueOnce(ME).mockRejectedValueOnce(new Error('blip'))
    const { result } = renderHook(() => useMe())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    await bumpLive(liveKeys.me)
    expect(resources.getMe).toHaveBeenCalledTimes(2)
    expect(result.current.status).toBe('ready')
    expect(result.current.name).toBe('Maya Krishnan')
  })

  it('does not fetch on a bump while offline', async () => {
    useAuthStore.setState({ user: { email: 'x@y.z' }, status: 'unauthenticated' })
    const { result } = renderHook(() => useMe())
    await bumpLive(liveKeys.me)
    expect(result.current.status).toBe('offline')
    expect(resources.getMe).not.toHaveBeenCalled()
  })
})
