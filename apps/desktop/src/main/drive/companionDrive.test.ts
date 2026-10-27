// SOLUSDEV-319 drive slice 3, review M3: the companion's drive lifecycle
// decisions, extracted from companion.ts so they are tested without a process.
import { describe, expect, it, vi } from 'vitest'
import {
  createDriveGeometryRelay,
  createSessionCourier,
  driveRespawnNeeded,
  driveSessionLine,
  folderChangeAction,
  SESSION_MAX_ATTEMPTS,
  SESSION_NEEDED_MIN_INTERVAL_MS,
  SESSION_RETRY_MS
} from './companionDrive'

const B = { x: 1, y: 2, width: 3, height: 4 }

describe('driveRespawnNeeded', () => {
  it('respawns a running child only when its baked agent socket differs', () => {
    expect(driveRespawnNeeded({ hasChild: true, bakedSocket: null }, '/s.sock')).toBe(true)
    expect(driveRespawnNeeded({ hasChild: true, bakedSocket: '/s.sock' }, null)).toBe(true)
    expect(driveRespawnNeeded({ hasChild: true, bakedSocket: '/s.sock' }, '/other.sock')).toBe(true)
    expect(driveRespawnNeeded({ hasChild: true, bakedSocket: '/s.sock' }, '/s.sock')).toBe(false)
    expect(driveRespawnNeeded({ hasChild: true, bakedSocket: null }, null)).toBe(false)
  })

  it('never with no child: the next spawn reads the fresh decision anyway', () => {
    expect(driveRespawnNeeded({ hasChild: false, bakedSocket: null }, '/s.sock')).toBe(false)
    expect(driveRespawnNeeded({ hasChild: true, bakedSocket: undefined }, '/s.sock')).toBe(false)
  })
})

describe('folderChangeAction', () => {
  const base = { activeProjectId: 'a', workspaceNow: '/w/a', workspaceBaked: '/w/a' }

  it('respawns when the active project workspace changed', () => {
    expect(folderChangeAction({ ...base, changedProjectId: 'a', workspaceNow: '/w/new' })).toBe(
      'respawn'
    )
  })

  it("re-checks drive for ANOTHER project's link change (the nested-folder rule)", () => {
    expect(folderChangeAction({ ...base, changedProjectId: 'b' })).toBe('recheck_drive')
  })

  it('re-checks drive (only) when the active link was rewritten to the same path', () => {
    expect(folderChangeAction({ ...base, changedProjectId: 'a' })).toBe('recheck_drive')
  })

  it('nothing without an active project', () => {
    expect(folderChangeAction({ ...base, activeProjectId: null, changedProjectId: 'a' })).toBe(
      'none'
    )
  })
})

describe('createDriveGeometryRelay', () => {
  it('forwards geometry only from the current child, spawned with drive', () => {
    const listener = vi.fn()
    const relay = createDriveGeometryRelay()
    relay.setListener(listener)
    const withDrive = {}
    const without = {}
    const onWithout = relay.attach(without, false)
    onWithout(B)
    expect(listener).not.toHaveBeenCalled() // spawned without drive: ignored
    const onWith = relay.attach(withDrive, true)
    onWithout(B) // the old child is no longer current
    onWith(B)
    expect(listener.mock.calls).toEqual([[B]])
  })

  it('detach (exit, replace, stop) clears the outline with null — for the current child only', () => {
    const listener = vi.fn()
    const relay = createDriveGeometryRelay()
    relay.setListener(listener)
    const old = {}
    const current = {}
    relay.attach(old, true)
    const onCurrent = relay.attach(current, true)
    relay.detach(old)
    expect(listener).not.toHaveBeenCalled()
    relay.detach(current)
    expect(listener.mock.calls).toEqual([[null]])
    onCurrent(B) // late output from a detached child
    expect(listener.mock.calls).toEqual([[null]])
  })

  it('a null listener is safe', () => {
    const relay = createDriveGeometryRelay()
    const child = {}
    relay.attach(child, true)(B)
    expect(() => relay.detach(child)).not.toThrow()
  })
})

describe('driveSessionLine', () => {
  it('is one newline-terminated drive_session frame', () => {
    expect(driveSessionLine({ socket: '/s/agent.sock', token: 'T' })).toBe(
      '{"type":"drive_session","socket":"/s/agent.sock","token":"T"}\n'
    )
  })
})

describe('createSessionCourier', () => {
  const GRANT = { socket: '/s/agent.sock', token: 'T'.repeat(43) }

  function courier(fetchResults: Array<typeof GRANT | null>): {
    c: ReturnType<typeof createSessionCourier>
    writes: Array<[object, string]>
    fetch: ReturnType<typeof vi.fn>
    timers: Array<{ cb: () => void; ms: number }>
    runTimers: () => Promise<void>
    advance: (ms: number) => void
  } {
    let t = 0
    const writes: Array<[object, string]> = []
    const timers: Array<{ cb: () => void; ms: number }> = []
    const fetch = vi.fn(async () =>
      fetchResults.length > 1 ? fetchResults.shift()! : fetchResults[0]
    )
    const c = createSessionCourier({
      fetch,
      write: (child, line) => void writes.push([child, line]),
      now: () => t,
      setTimeout: (cb, ms) => {
        timers.push({ cb, ms })
        return timers.length
      },
      clearTimeout: () => void timers.splice(0)
    })
    return {
      c,
      writes,
      fetch,
      timers,
      advance: (ms) => void (t += ms),
      runTimers: async () => {
        for (const timer of timers.splice(0)) timer.cb()
        await flush()
      }
    }
  }
  const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

  it('delivers a session to a freshly spawned child', async () => {
    const h = courier([GRANT])
    const child = {}
    h.c.start(child)
    await flush()
    expect(h.writes).toEqual([[child, driveSessionLine(GRANT)]])
  })

  it('retries while the agent is not up yet (just registered, still starting)', async () => {
    const h = courier([null, null, GRANT])
    const child = {}
    h.c.start(child)
    await flush()
    expect(h.writes).toEqual([])
    expect(h.timers[0].ms).toBe(SESSION_RETRY_MS)
    await h.runTimers()
    await h.runTimers()
    expect(h.writes).toEqual([[child, driveSessionLine(GRANT)]])
  })

  it('gives up after a bounded number of attempts', async () => {
    const h = courier([null])
    h.c.start({})
    await flush()
    for (let i = 0; i < SESSION_MAX_ATTEMPTS + 5; i++) await h.runTimers()
    expect(h.fetch).toHaveBeenCalledTimes(SESSION_MAX_ATTEMPTS)
  })

  it('never writes to a child that was stopped or replaced while the fetch ran', async () => {
    const h = courier([GRANT])
    const old = {}
    h.c.start(old)
    h.c.stop(old)
    await flush()
    const next = {}
    h.c.start(next)
    h.c.start({}) // replaced again before its fetch returned
    await flush()
    expect(h.writes.map(([c]) => c)).not.toContain(old)
    expect(h.writes.map(([c]) => c)).not.toContain(next)
  })

  it('drive_session_needed re-sends, at most once per interval, and only for the current child', async () => {
    const h = courier([GRANT])
    const child = {}
    h.c.start(child)
    await flush()
    h.c.needed(child)
    h.c.needed(child) // inside the interval: ignored
    h.c.needed({}) // not the current child
    await flush()
    expect(h.writes).toHaveLength(2)
    h.advance(SESSION_NEEDED_MIN_INTERVAL_MS)
    h.c.needed(child)
    await flush()
    expect(h.writes).toHaveLength(3)
  })
})
