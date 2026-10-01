import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  LIVE_COALESCE_MS,
  liveKeys,
  resetLiveRevisions,
  useLiveRevision,
  useLiveRevisionStore
} from './liveRevisionStore'

const state = (): ReturnType<typeof useLiveRevisionStore.getState> =>
  useLiveRevisionStore.getState()

beforeEach(() => {
  vi.useFakeTimers()
  resetLiveRevisions()
})
afterEach(() => {
  resetLiveRevisions()
  vi.useRealTimers()
})

describe('liveKeys', () => {
  it('builds distinct, stable keys', () => {
    const keys = [
      liveKeys.me,
      liveKeys.teams,
      liveKeys.notifications,
      liveKeys.team('a'),
      liveKeys.teamMembers('a'),
      liveKeys.teamInvites('a'),
      liveKeys.teamProjects('a'),
      liveKeys.teamActivity('a'),
      liveKeys.projectDetail('p'),
      liveKeys.projectSources('p'),
      liveKeys.projectLayout('p'),
      liveKeys.projectJobs('p')
    ]
    expect(new Set(keys).size).toBe(keys.length)
    expect(liveKeys.team('a')).toBe(liveKeys.team('a'))
    expect(liveKeys.team('a')).not.toBe(liveKeys.team('b'))
  })
  it('puts every per-team key under one prefix so account-wide revalidation can match them', () => {
    for (const key of [
      liveKeys.team('a'),
      liveKeys.teamMembers('a'),
      liveKeys.teamInvites('a'),
      liveKeys.teamProjects('a'),
      liveKeys.teamActivity('a')
    ])
      expect(liveKeys.isTeamKey(key)).toBe(true)
    expect(liveKeys.isTeamKey(liveKeys.me)).toBe(false)
    expect(liveKeys.isTeamKey(liveKeys.projectDetail('p'))).toBe(false)
  })
})

describe('liveRevisionStore', () => {
  it('starts every key at revision 0', () => {
    expect(state().revisions).toEqual({})
    const view = renderHook(() => useLiveRevision(liveKeys.me))
    expect(view.result.current).toBe(0)
  })

  it('bump increments only the named keys, after the coalescing window', () => {
    state().bump([liveKeys.me, liveKeys.teams])
    expect(state().revisions).toEqual({})
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    expect(state().revisions).toEqual({ [liveKeys.me]: 1, [liveKeys.teams]: 1 })
  })

  it('coalesces a burst into one store update and one increment per key', () => {
    const listener = vi.fn()
    const unsubscribe = useLiveRevisionStore.subscribe(listener)
    for (let i = 0; i < 20; i += 1) state().bump([liveKeys.notifications])
    state().bump([liveKeys.me])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS * 4))
    expect(listener).toHaveBeenCalledTimes(1)
    expect(state().revisions[liveKeys.notifications]).toBe(1)
    expect(state().revisions[liveKeys.me]).toBe(1)
    unsubscribe()
  })

  it('a later burst after the window increments again', () => {
    state().bump([liveKeys.me])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    state().bump([liveKeys.me])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    expect(state().revisions[liveKeys.me]).toBe(2)
  })

  it('replaces the revisions object instead of mutating it', () => {
    state().bump([liveKeys.me])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    const before = state().revisions
    const snapshot = { ...before }
    state().bump([liveKeys.teams])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    expect(state().revisions).not.toBe(before)
    expect(before).toEqual(snapshot)
    expect(Object.isFrozen(before)).toBe(true)
  })

  it('bumpWhere revalidates every known key matching the predicate, coalesced with bump', () => {
    state().bump([liveKeys.team('a'), liveKeys.team('b'), liveKeys.me])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    state().bumpWhere(liveKeys.isTeamKey)
    state().bump([liveKeys.team('a')])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    expect(state().revisions[liveKeys.team('a')]).toBe(2)
    expect(state().revisions[liveKeys.team('b')]).toBe(2)
    expect(state().revisions[liveKeys.me]).toBe(1)
  })

  it('bumpWhere with no matching keys changes nothing and emits nothing', () => {
    const listener = vi.fn()
    useLiveRevisionStore.subscribe(listener)
    state().bumpWhere(() => false)
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    expect(listener).not.toHaveBeenCalled()
  })

  it('bump of an empty list is a no-op', () => {
    const listener = vi.fn()
    useLiveRevisionStore.subscribe(listener)
    state().bump([])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    expect(listener).not.toHaveBeenCalled()
  })

  it('the selector hook re-renders only for its own key', () => {
    let renders = 0
    const view = renderHook(() => {
      renders += 1
      return useLiveRevision(liveKeys.teams)
    })
    const before = renders
    state().bump([liveKeys.me])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    expect(renders).toBe(before)
    state().bump([liveKeys.teams])
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS))
    expect(view.result.current).toBe(1)
  })

  it('useLiveRevision(null) is a constant 0', () => {
    const view = renderHook(() => useLiveRevision(null))
    expect(view.result.current).toBe(0)
  })

  it('records the newest layout version per project, never moving backwards', () => {
    state().recordLayoutVersion('p', 5)
    state().recordLayoutVersion('p', 3)
    state().recordLayoutVersion('q', 1)
    expect(state().layoutVersions).toEqual({ p: 5, q: 1 })
    state().recordLayoutVersion('p', 6)
    expect(state().layoutVersions.p).toBe(6)
  })

  it('tracks the account stream status', () => {
    expect(state().accountStream).toBe('idle')
    state().setAccountStream('live')
    expect(state().accountStream).toBe('live')
  })

  it('reset drops pending bumps as well as state', () => {
    state().bump([liveKeys.me])
    resetLiveRevisions()
    act(() => void vi.advanceTimersByTime(LIVE_COALESCE_MS * 2))
    expect(state().revisions).toEqual({})
  })
})
