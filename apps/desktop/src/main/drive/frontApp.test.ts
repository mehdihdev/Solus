// SOLUSDEV-319 slice 4 (docs/architecture/sol-drive.md §2.2 "Main: summon
// snapshot and relay"): on every pill summon main runs ONE identify through the
// drive transport before the pill takes focus, waits at most 250 ms, and keeps
// the reply's front as the snapshot — kept over Solus itself, cleared on drive
// off / project switch / companion restart or exit, null when unavailable.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createFrontAppLink,
  createFrontAppTracker,
  FRONT_APP_SUMMON_WAIT_MS,
  type FrontAppContext
} from './frontApp'
import type { SolFrontApp } from './frontAppShape'
import type { DriveOp, DriveTransport } from './driveTransport'

const FREECAD = {
  drivable: true,
  binding: 'window',
  bundleId: 'org.freecad.FreeCAD',
  name: 'FreeCAD',
  pid: 4242,
  windowId: 77,
  title: 'bracket_v3.FCStd',
  bounds: { x: 0, y: 0, width: 10, height: 10 },
  documentDir: null
}
const SOLUS = {
  drivable: false,
  binding: null,
  bundleId: 'com.solusforge.solus',
  name: 'Solus',
  reason: 'denied'
}
const identifyReply = (front: unknown): Record<string, unknown> => ({
  ok: true,
  now: 1,
  trust: { accessibility: true, screenRecording: true },
  unsignedDev: false,
  front
})

function harness(opts: { context?: FrontAppContext | null; transport?: DriveTransport | null }): {
  tracker: ReturnType<typeof createFrontAppTracker>
  published: Array<SolFrontApp | null>
  setContext(next: FrontAppContext | null): void
} {
  let context = opts.context === undefined ? { workspace: null } : opts.context
  const published: Array<SolFrontApp | null> = []
  const tracker = createFrontAppTracker({
    context: () => context,
    transport: () => (opts.transport === undefined ? null : opts.transport),
    publish: (front) => void published.push(front),
    setTimeout: (cb, ms) => setTimeout(cb, ms),
    clearTimeout: (handle) => clearTimeout(handle as NodeJS.Timeout)
  })
  return { tracker, published, setContext: (next) => void (context = next) }
}

const answering = (...replies: unknown[]): DriveTransport & { calls: DriveOp[] } => {
  const calls: DriveOp[] = []
  return {
    calls,
    request: vi.fn(async (op: DriveOp) => {
      calls.push(op)
      return identifyReply(replies.shift() ?? null)
    })
  }
}

beforeEach(() => void vi.useFakeTimers())
afterEach(() => void vi.useRealTimers())

describe('createFrontAppTracker — the summon snapshot', () => {
  it('runs one identify and keeps only the renderer fields of its front', async () => {
    const transport = answering(FREECAD)
    const h = harness({ transport })
    await h.tracker.beforeSummon()
    expect(transport.calls).toEqual([{ op: 'run', argv: ['identify'] }])
    const expected = {
      drivable: true,
      binding: 'window',
      bundleId: 'org.freecad.FreeCAD',
      name: 'FreeCAD',
      pid: 4242,
      windowId: 77,
      title: 'bracket_v3.FCStd'
    }
    expect(h.tracker.snapshot()).toEqual(expected)
    expect(h.published).toEqual([expected])
  })

  it('passes --within when the drive child has a workspace', async () => {
    const transport = answering(FREECAD)
    const h = harness({ transport, context: { workspace: '/w/rover' } })
    await h.tracker.beforeSummon()
    expect(transport.calls[0]).toEqual({ op: 'run', argv: ['identify', '--within', '/w/rover'] })
  })

  it('is null, without asking the helper, when driving is off or unavailable', async () => {
    const transport = answering(FREECAD)
    const h = harness({ transport, context: null })
    await h.tracker.beforeSummon()
    expect(transport.calls).toEqual([])
    expect(h.tracker.snapshot()).toBeNull()
  })

  it('is null when the transport is missing, fails or answers a refusal', async () => {
    for (const transport of [
      null,
      { request: async () => null },
      { request: async () => ({ ok: false, code: 'usage' }) },
      { request: async () => identifyReply({ bundleId: 'bad id' }) }
    ]) {
      const h = harness({ transport, context: { workspace: null } })
      await h.tracker.beforeSummon()
      expect(h.tracker.snapshot()).toBeNull()
    }
  })

  it('a denied app is stored as bundleId + name + drivable:false only', async () => {
    const terminal = { ...SOLUS, bundleId: 'com.apple.Terminal', name: 'Terminal' }
    const h = harness({ transport: answering(terminal) })
    await h.tracker.beforeSummon()
    expect(h.tracker.snapshot()).toEqual({
      drivable: false,
      binding: null,
      bundleId: 'com.apple.Terminal',
      name: 'Terminal'
    })
  })

  it('truncates the title to 256 scalars', async () => {
    const h = harness({ transport: answering({ ...FREECAD, title: 'x'.repeat(400) }) })
    await h.tracker.beforeSummon()
    const front = h.tracker.snapshot()
    expect(front?.drivable && front.title).toBe('x'.repeat(256))
  })

  it('summoning over Solus keeps the previous snapshot', async () => {
    const h = harness({ transport: answering(FREECAD, SOLUS) })
    await h.tracker.beforeSummon()
    const before = h.tracker.snapshot()
    await h.tracker.beforeSummon()
    expect(h.tracker.snapshot()).toEqual(before)
    expect(h.published).toHaveLength(1)
  })

  it('nothing in front replaces the snapshot with null', async () => {
    const h = harness({ transport: answering(FREECAD, null) })
    await h.tracker.beforeSummon()
    await h.tracker.beforeSummon()
    expect(h.tracker.snapshot()).toBeNull()
  })
})

describe('createFrontAppTracker — the 250 ms wait', () => {
  it('resolves after 250 ms when identify has not answered, aborts it and discards a late reply', async () => {
    let resolveLate: (v: Record<string, unknown>) => void = () => undefined
    let signal: AbortSignal | null = null
    const transport: DriveTransport = {
      request: (_op, s) => {
        signal = s
        return new Promise((r) => (resolveLate = r))
      }
    }
    const h = harness({ transport })
    const summon = h.tracker.beforeSummon()
    let done = false
    void summon.then(() => (done = true))
    await vi.advanceTimersByTimeAsync(FRONT_APP_SUMMON_WAIT_MS - 1)
    expect(done).toBe(false)
    await vi.advanceTimersByTimeAsync(1)
    expect(done).toBe(true)
    expect(signal!.aborted).toBe(true)
    resolveLate(identifyReply(FREECAD))
    await vi.advanceTimersByTimeAsync(0)
    expect(h.tracker.snapshot()).toBeNull()
  })
})

describe('createFrontAppTracker — clearing', () => {
  it('clear() empties the snapshot and publishes null once', async () => {
    const h = harness({ transport: answering(FREECAD) })
    await h.tracker.beforeSummon()
    h.tracker.clear()
    h.tracker.clear()
    expect(h.tracker.snapshot()).toBeNull()
    expect(h.published).toEqual([expect.objectContaining({ pid: 4242 }), null])
  })

  it('a reply in flight when the snapshot is cleared (drive off) is discarded', async () => {
    let answer: (v: Record<string, unknown>) => void = () => undefined
    const h = harness({ transport: { request: () => new Promise((r) => (answer = r)) } })
    const summon = h.tracker.beforeSummon()
    h.tracker.clear()
    answer(identifyReply(FREECAD))
    await summon
    expect(h.tracker.snapshot()).toBeNull()
  })
})

describe('createFrontAppLink — the relay ↔ tracker seam', () => {
  it('a new or exited drive child (companion restart/exit) clears the snapshot', async () => {
    const h = harness({ transport: answering(FREECAD, FREECAD) })
    const link = createFrontAppLink()
    link.setTracker(h.tracker)
    await h.tracker.beforeSummon()
    link.setDriveChild({ workspace: null })
    expect(link.snapshot()).toBeNull()
    expect(link.driveChild()).toEqual({ workspace: null })
    await h.tracker.beforeSummon()
    link.setDriveChild(null)
    expect(link.snapshot()).toBeNull()
    expect(link.driveChild()).toBeNull()
  })

  it('without a tracker the snapshot is null', () => {
    expect(createFrontAppLink().snapshot()).toBeNull()
  })
})
