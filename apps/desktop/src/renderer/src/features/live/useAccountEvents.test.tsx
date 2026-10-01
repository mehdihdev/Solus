import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AccountEvent } from '../../lib/api/accountEvents'
import { streamAccountEvents } from '../../lib/api/accountEvents'
import { LiveStreamHttpError } from '../../lib/api/liveStream'
import { useAuthStore } from '../../store/authStore'
import { useWorkspaceStore } from '../../store/workspaceStore'
import {
  LIVE_COALESCE_MS,
  liveKeys,
  resetLiveRevisions,
  useLiveRevisionStore
} from '../../store/liveRevisionStore'
import { useAccountEvents } from './useAccountEvents'

vi.mock('../../lib/api/accountEvents', () => ({ streamAccountEvents: vi.fn() }))

const T = 'team-1'
const P = 'proj-1'
const AT = 'now'
const ready: AccountEvent = { type: 'ready', user_id: 'u', team_ids: [T, 'team-2'] }
const TEAM_KEYS = (id: string): string[] => [
  liveKeys.team(id),
  liveKeys.teamMembers(id),
  liveKeys.teamInvites(id),
  liveKeys.teamProjects(id),
  liveKeys.teamActivity(id)
]

/** A stream that delivers `events` once, then idles until aborted. */
function stream(events: AccountEvent[]): void {
  vi.mocked(streamAccountEvents).mockImplementation(async function* (signal) {
    for (const event of events) yield event
    await new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve()))
  })
}
async function settle(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(LIVE_COALESCE_MS)
  })
}
const revisions = (): Readonly<Record<string, number>> => useLiveRevisionStore.getState().revisions
const bumped = (): string[] =>
  Object.entries(revisions())
    .filter(([, value]) => value > 0)
    .map(([key]) => key)
    .sort()

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  resetLiveRevisions()
  useWorkspaceStore.setState({ linked: false })
  useAuthStore.setState({
    status: 'authenticated',
    accessToken: 'tok-1',
    user: { email: 'a@b.c' }
  })
})
afterEach(() => {
  resetLiveRevisions()
  vi.useRealTimers()
})

describe('useAccountEvents mapping', () => {
  it('ready revalidates every account-scoped key, including known team keys', async () => {
    // A team key the account has never been told about is still revalidated.
    useLiveRevisionStore.getState().bump([liveKeys.team('unlisted')])
    await settle()
    stream([ready])
    renderHook(() => useAccountEvents())
    await settle()
    expect(bumped()).toEqual(
      [
        liveKeys.me,
        liveKeys.teams,
        liveKeys.notifications,
        ...TEAM_KEYS(T),
        ...TEAM_KEYS('team-2'),
        liveKeys.team('unlisted')
      ].sort()
    )
    expect(revisions()[liveKeys.team('unlisted')]).toBe(2)
  })

  it.each<[string, AccountEvent, string[]]>([
    [
      'team.updated',
      { type: 'team.updated', team_id: T, at: AT },
      [liveKeys.team(T), liveKeys.teams]
    ],
    [
      'team.members_changed',
      { type: 'team.members_changed', team_id: T, at: AT },
      [liveKeys.teamMembers(T)]
    ],
    [
      'team.invites_changed',
      { type: 'team.invites_changed', team_id: T, at: AT },
      [liveKeys.teamInvites(T)]
    ],
    [
      'team.projects_changed without project',
      { type: 'team.projects_changed', team_id: T, project_id: null, at: AT },
      [liveKeys.teamProjects(T)]
    ],
    [
      'team.projects_changed with project',
      { type: 'team.projects_changed', team_id: T, project_id: P, at: AT },
      [liveKeys.teamProjects(T), liveKeys.projectDetail(P)]
    ],
    [
      'team.activity',
      { type: 'team.activity', team_id: T, project_id: null, actor_id: 'x', at: AT },
      [liveKeys.teamActivity(T)]
    ],
    [
      'notification.created',
      { type: 'notification.created', user_id: 'u', at: AT },
      [liveKeys.notifications]
    ],
    [
      'membership.changed',
      { type: 'membership.changed', user_id: 'u', team_id: T, project_id: null, at: AT },
      [liveKeys.me, liveKeys.teams, ...TEAM_KEYS(T)]
    ],
    [
      'membership.changed without team',
      { type: 'membership.changed', user_id: 'u', team_id: null, project_id: null, at: AT },
      [liveKeys.me, liveKeys.teams]
    ],
    [
      'access.revoked',
      { type: 'access.revoked', user_id: 'u', team_id: T, project_id: P, at: AT },
      [liveKeys.me, liveKeys.teams, liveKeys.projectDetail(P), ...TEAM_KEYS(T)]
    ]
  ])('%s bumps exactly its keys', async (_name, event, expected) => {
    stream([event])
    renderHook(() => useAccountEvents())
    await settle()
    expect(bumped()).toEqual([...expected].sort())
  })

  it('ready then a burst of frames coalesces into one increment per key', async () => {
    stream([
      ready,
      { type: 'team.members_changed', team_id: T, at: AT },
      { type: 'team.members_changed', team_id: T, at: AT }
    ])
    renderHook(() => useAccountEvents())
    await settle()
    expect(revisions()[liveKeys.teamMembers(T)]).toBe(1)
  })

  it('raises no toast or DOM event: a quiet refresh', async () => {
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    stream([ready, { type: 'notification.created', user_id: 'u', at: AT }])
    renderHook(() => useAccountEvents())
    await settle()
    expect(dispatch).not.toHaveBeenCalled()
  })
})

describe('useAccountEvents lifecycle', () => {
  it('does not open a stream while signed out or token-less', async () => {
    useAuthStore.setState({ status: 'unauthenticated', accessToken: null, user: null })
    renderHook(() => useAccountEvents())
    await settle()
    expect(streamAccountEvents).not.toHaveBeenCalled()
    expect(useLiveRevisionStore.getState().accountStream).toBe('idle')
  })

  it('tracks status: connecting, live after ready, idle after unmount', async () => {
    stream([])
    const view = renderHook(() => useAccountEvents())
    await act(async () => {})
    expect(useLiveRevisionStore.getState().accountStream).toBe('connecting')
    view.unmount()
    expect(useLiveRevisionStore.getState().accountStream).toBe('idle')

    stream([ready])
    const second = renderHook(() => useAccountEvents())
    await settle()
    expect(useLiveRevisionStore.getState().accountStream).toBe('live')
    second.unmount()
  })

  it('aborts on unmount', async () => {
    stream([])
    const view = renderHook(() => useAccountEvents())
    await act(async () => {})
    const signal = vi.mocked(streamAccountEvents).mock.calls[0]?.[0]
    view.unmount()
    expect(signal?.aborted).toBe(true)
  })

  it('aborts on sign-out and does not reconnect', async () => {
    stream([])
    renderHook(() => useAccountEvents())
    await act(async () => {})
    const signal = vi.mocked(streamAccountEvents).mock.calls[0]?.[0]
    act(() => useAuthStore.setState({ status: 'unauthenticated', accessToken: null, user: null }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000)
    })
    expect(signal?.aborted).toBe(true)
    expect(streamAccountEvents).toHaveBeenCalledTimes(1)
    expect(useLiveRevisionStore.getState().accountStream).toBe('idle')
  })

  it('restarts the stream when the token changes', async () => {
    stream([])
    renderHook(() => useAccountEvents())
    await act(async () => {})
    const first = vi.mocked(streamAccountEvents).mock.calls[0]?.[0]
    act(() => useAuthStore.setState({ accessToken: 'tok-2' }))
    await act(async () => {})
    expect(first?.aborted).toBe(true)
    expect(streamAccountEvents).toHaveBeenCalledTimes(2)
  })

  it('restarts for a different user and drops late frames from the old session', async () => {
    let release: () => void = () => undefined
    vi.mocked(streamAccountEvents).mockImplementationOnce(async function* () {
      await new Promise<void>((resolve) => {
        release = resolve
      })
      yield { type: 'notification.created', user_id: 'old', at: AT } as AccountEvent
    })
    stream([])
    renderHook(() => useAccountEvents())
    await act(async () => {})
    act(() => useAuthStore.setState({ user: { email: 'other@b.c' }, accessToken: 'tok-9' }))
    await act(async () => {})
    await act(async () => release())
    await settle()
    expect(revisions()[liveKeys.notifications]).toBeUndefined()
    expect(streamAccountEvents).toHaveBeenCalledTimes(2)
  })

  it('reconnects with backoff after a server error and revalidates on the next ready', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.99)
    vi.mocked(streamAccountEvents).mockImplementationOnce(async function* () {
      throw new LiveStreamHttpError(503)
      yield ready
    })
    stream([ready])
    renderHook(() => useAccountEvents())
    await act(async () => {})
    expect(useLiveRevisionStore.getState().accountStream).toBe('reconnecting')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000)
    })
    await settle()
    expect(streamAccountEvents).toHaveBeenCalledTimes(2)
    expect(useLiveRevisionStore.getState().accountStream).toBe('live')
    expect(revisions()[liveKeys.me]).toBe(1)
    vi.mocked(Math.random).mockRestore()
  })

  it('stops for good on 403 and on 429-free permission loss, status stopped', async () => {
    vi.mocked(streamAccountEvents).mockImplementation(async function* () {
      throw new LiveStreamHttpError(403)
      yield ready
    })
    renderHook(() => useAccountEvents())
    await act(async () => {})
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000)
    })
    expect(streamAccountEvents).toHaveBeenCalledTimes(1)
    expect(useLiveRevisionStore.getState().accountStream).toBe('stopped')
  })

  it('on 401 waits for a token change instead of retrying, then resumes', async () => {
    vi.mocked(streamAccountEvents).mockImplementationOnce(async function* () {
      throw new LiveStreamHttpError(401)
      yield ready
    })
    stream([ready])
    renderHook(() => useAccountEvents())
    await act(async () => {})
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000)
    })
    expect(streamAccountEvents).toHaveBeenCalledTimes(1)
    expect(useLiveRevisionStore.getState().accountStream).toBe('stopped')
    act(() => useAuthStore.setState({ accessToken: 'refreshed' }))
    await settle()
    expect(streamAccountEvents).toHaveBeenCalledTimes(2)
    expect(useLiveRevisionStore.getState().accountStream).toBe('live')
  })

  it('keeps retrying 429 with backoff', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.99)
    vi.mocked(streamAccountEvents).mockImplementation(async function* () {
      throw new LiveStreamHttpError(429)
      yield ready
    })
    renderHook(() => useAccountEvents())
    await act(async () => {})
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000)
    })
    expect(streamAccountEvents).toHaveBeenCalledTimes(2)
    vi.mocked(Math.random).mockRestore()
  })
})
