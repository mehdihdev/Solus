// SOLUSDEV-223 (SOL-IPC-01) — the main-process end of the orb↔overlay push
// wire. These tests exercise validation, sender filtering, and teardown
// against structural fakes of BrowserWindow/ipcMain (the companion.ts
// pattern); the live contextIsolation round-trip is on the COWORK QA
// checklist, not in vitest.
import { describe, it, expect, vi } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { BrowserWindow, IpcMain } from 'electron'
import { ORB_OVERLAY_CHANNELS, type OrbToOverlay, type OverlayToOrb } from '@solus/shared-types'
import {
  attachOrbOverlayWire,
  type OrbOverlayWire,
  type WireIpc,
  type WireIpcEvent,
  type WireWindow
} from './orbOverlayWire'

const STEP = {
  stepId: 'sketch-1',
  index: 1,
  total: 3,
  title: 'Open the sketch',
  instruction: 'Click the sketch button in the toolbar',
  control: null
}

const ADVANCE: OrbToOverlay = { type: 'advance', handoffId: 'h-1', step: STEP }
const READY: OverlayToOrb = { type: 'ready', handoffId: 'h-1' }
const FAILED: OverlayToOrb = { type: 'failed', handoffId: 'h-1', reason: 'window not found' }
const MALFORMED = { type: 'advance', handoffId: 'h-1', step: null }
const UNKNOWN_TYPE = { type: 'exfiltrate', handoffId: 'h-1' }

function fakeWindow(id = 7): {
  win: WireWindow
  sent: Array<{ channel: string; message: unknown }>
  closedListenerCount: () => number
  close: () => void
  destroy: () => void
  revokeWebContents: () => void
} {
  const sent: Array<{ channel: string; message: unknown }> = []
  const closedListeners = new Set<() => void>()
  let destroyed = false
  let revoked = false
  const webContents = {
    id,
    send: (channel: string, message: unknown): void => {
      sent.push({ channel, message })
    }
  }
  const win: WireWindow = {
    isDestroyed: () => destroyed,
    once: (_event, listener) => {
      closedListeners.add(listener)
    },
    off: (_event, listener) => {
      closedListeners.delete(listener)
    },
    get webContents() {
      if (revoked) throw new Error('webContents destroyed')
      return webContents
    }
  }
  return {
    win,
    sent,
    closedListenerCount: () => closedListeners.size,
    close: () => {
      destroyed = true
      for (const listener of [...closedListeners]) listener()
    },
    destroy: () => {
      destroyed = true
    },
    revokeWebContents: () => {
      revoked = true
    }
  }
}

type IpcListener = (event: WireIpcEvent, raw: unknown) => void

function fakeIpc(): {
  ipc: WireIpc
  emit: (channel: string, senderId: number, raw: unknown) => void
  count: (channel: string) => number
} {
  const listeners = new Map<string, Set<IpcListener>>()
  return {
    ipc: {
      on: (channel, listener) => {
        const set = listeners.get(channel) ?? new Set()
        set.add(listener)
        listeners.set(channel, set)
      },
      removeListener: (channel, listener) => {
        listeners.get(channel)?.delete(listener)
      }
    },
    emit: (channel, senderId, raw) => {
      for (const listener of [...(listeners.get(channel) ?? [])]) {
        listener({ sender: { id: senderId } }, raw)
      }
    },
    count: (channel) => listeners.get(channel)?.size ?? 0
  }
}

describe('outbound pushes', () => {
  it('pushToOrb validates and sends a fresh parsed message on the toOrb channel', () => {
    const w = fakeWindow()
    const wire = attachOrbOverlayWire(w.win, fakeIpc().ipc)
    expect(wire.pushToOrb(READY)).toBe(true)
    expect(w.sent).toHaveLength(1)
    expect(w.sent[0].channel).toBe(ORB_OVERLAY_CHANNELS.toOrb)
    expect(w.sent[0].message).toEqual(READY)
    // Parsers rebuild every field; the caller's object never crosses as-is.
    expect(w.sent[0].message).not.toBe(READY)
  })

  it('pushToOverlay validates and sends on the toOverlay channel', () => {
    const w = fakeWindow()
    const wire = attachOrbOverlayWire(w.win, fakeIpc().ipc)
    expect(wire.pushToOverlay(ADVANCE)).toBe(true)
    expect(w.sent[0].channel).toBe(ORB_OVERLAY_CHANNELS.toOverlay)
    expect(w.sent[0].message).toEqual(ADVANCE)
  })

  it('a malformed outbound message throws — a bug in our own process is loud', () => {
    const w = fakeWindow()
    const wire = attachOrbOverlayWire(w.win, fakeIpc().ipc)
    expect(() => wire.pushToOverlay(MALFORMED as unknown as OrbToOverlay)).toThrow(TypeError)
    expect(() => wire.pushToOrb(UNKNOWN_TYPE as unknown as OverlayToOrb)).toThrow(TypeError)
    expect(w.sent).toHaveLength(0)
  })

  it('pushes to a destroyed window are dropped, not crashed (the after-dismiss race)', () => {
    const w = fakeWindow()
    const wire = attachOrbOverlayWire(w.win, fakeIpc().ipc)
    w.destroy()
    expect(wire.pushToOrb(READY)).toBe(false)
    expect(w.sent).toHaveLength(0)
  })
})

describe('inbound subscriptions', () => {
  it('delivers a valid renderer message, parsed', () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const wire = attachOrbOverlayWire(w.win, i.ipc)
    const seen: OrbToOverlay[] = []
    wire.onOrbToOverlay((m) => seen.push(m))
    i.emit(ORB_OVERLAY_CHANNELS.toOverlay, 7, ADVANCE)
    expect(seen).toEqual([ADVANCE])
    expect(seen[0]).not.toBe(ADVANCE)
  })

  it('rejects a malformed message at the boundary: handler never runs, rejection observable', () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const onMalformed = vi.fn()
    const wire = attachOrbOverlayWire(w.win, i.ipc, onMalformed)
    const handler = vi.fn()
    wire.onOrbToOverlay(handler)
    wire.onOverlayToOrb(handler)
    i.emit(ORB_OVERLAY_CHANNELS.toOverlay, 7, MALFORMED)
    i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, UNKNOWN_TYPE)
    i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, 'not even an object')
    expect(handler).not.toHaveBeenCalled()
    expect(onMalformed).toHaveBeenCalledTimes(3)
    expect(onMalformed).toHaveBeenCalledWith(ORB_OVERLAY_CHANNELS.toOverlay, expect.any(TypeError))
  })

  it('screens a hostile megabyte `type` field before it can bloat an error message', () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const onMalformed = vi.fn()
    const wire = attachOrbOverlayWire(w.win, i.ipc, onMalformed)
    const handler = vi.fn()
    wire.onOverlayToOrb(handler)
    i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, { type: 'A'.repeat(1_000_000), handoffId: 'h-1' })
    expect(handler).not.toHaveBeenCalled()
    expect(onMalformed).toHaveBeenCalledTimes(1)
    const error = onMalformed.mock.calls[0][1] as Error
    expect(error.message.length).toBeLessThan(256)
  })

  it('the default logger strips control characters and throttles a malformed flood', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const w = fakeWindow(7)
      const i = fakeIpc()
      const wire = attachOrbOverlayWire(w.win, i.ipc)
      wire.onOverlayToOrb(vi.fn())
      i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, {
        type: 'x\nFORGED ENTRY — user confirmed flash',
        handoffId: 'h-1'
      })
      expect(spy).toHaveBeenCalledTimes(1)
      expect(spy.mock.calls[0].join(' ')).not.toMatch(/[\n\r]/)
      for (let k = 0; k < 10; k += 1) {
        i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, { type: 'nope', handoffId: 'h-1' })
      }
      // 11 malformed messages, at most MALFORMED_LOG_CAP log lines.
      expect(spy.mock.calls.length).toBeLessThanOrEqual(5)
    } finally {
      spy.mockRestore()
    }
  })

  it('a __proto__-smuggling payload is delivered clean and pollutes nothing', () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const wire = attachOrbOverlayWire(w.win, i.ipc)
    const seen: OverlayToOrb[] = []
    wire.onOverlayToOrb((m) => seen.push(m))
    const raw: unknown = JSON.parse(
      '{"__proto__":{"polluted":true},"type":"ready","handoffId":"h-1"}'
    )
    i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, raw)
    expect(seen).toEqual([READY])
    expect(({} as { polluted?: unknown }).polluted).toBeUndefined()
  })

  it("ignores messages from another window's webContents", () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const wire = attachOrbOverlayWire(w.win, i.ipc)
    const handler = vi.fn()
    wire.onOverlayToOrb(handler)
    i.emit(ORB_OVERLAY_CHANNELS.toOrb, 99, FAILED)
    expect(handler).not.toHaveBeenCalled()
    i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, FAILED)
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('inbound filtering never touches webContents after attach (renderer-crash safety)', () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const wire = attachOrbOverlayWire(w.win, i.ipc)
    const handler = vi.fn()
    wire.onOverlayToOrb(handler)
    w.revokeWebContents()
    i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, READY)
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('unsubscribe removes the underlying ipc listener', () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const wire = attachOrbOverlayWire(w.win, i.ipc)
    const handler = vi.fn()
    const unsubscribe = wire.onOverlayToOrb(handler)
    expect(i.count(ORB_OVERLAY_CHANNELS.toOrb)).toBe(1)
    unsubscribe()
    expect(i.count(ORB_OVERLAY_CHANNELS.toOrb)).toBe(0)
    i.emit(ORB_OVERLAY_CHANNELS.toOrb, 7, READY)
    expect(handler).not.toHaveBeenCalled()
    // A second call is a no-op, not a double-remove.
    unsubscribe()
  })
})

describe('teardown', () => {
  it('window close removes every ipc listener and kills pushes — a listener must not survive its BrowserWindow', () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const wire = attachOrbOverlayWire(w.win, i.ipc)
    const handler = vi.fn()
    wire.onOrbToOverlay(handler)
    wire.onOverlayToOrb(handler)
    w.close()
    expect(i.count(ORB_OVERLAY_CHANNELS.toOverlay)).toBe(0)
    expect(i.count(ORB_OVERLAY_CHANNELS.toOrb)).toBe(0)
    expect(wire.pushToOrb(READY)).toBe(false)
    expect(w.sent).toHaveLength(0)
  })

  it('subscribing on a closed wire throws instead of silently leaking', () => {
    const w = fakeWindow()
    const wire = attachOrbOverlayWire(w.win, fakeIpc().ipc)
    w.close()
    expect(() => wire.onOrbToOverlay(() => {})).toThrow(/closed/)
  })

  it('attaching to an already-destroyed window registers nothing and stays inert', () => {
    const w = fakeWindow()
    w.destroy()
    const wire = attachOrbOverlayWire(w.win, fakeIpc().ipc)
    expect(w.closedListenerCount()).toBe(0)
    expect(wire.pushToOrb(READY)).toBe(false)
    expect(() => wire.onOrbToOverlay(() => {})).toThrow(/closed/)
  })

  it('detach() is idempotent, removes the closed hook, and re-attachment does not accumulate listeners', () => {
    const w = fakeWindow(7)
    const i = fakeIpc()
    const wire = attachOrbOverlayWire(w.win, i.ipc)
    wire.onOverlayToOrb(vi.fn())
    expect(w.closedListenerCount()).toBe(1)
    wire.detach()
    wire.detach()
    expect(w.closedListenerCount()).toBe(0)
    expect(i.count(ORB_OVERLAY_CHANNELS.toOrb)).toBe(0)
    expect(wire.pushToOverlay(ADVANCE)).toBe(false)
    attachOrbOverlayWire(w.win, i.ipc)
    expect(w.closedListenerCount()).toBe(1)
  })
})

describe('channel-literal ratchet', () => {
  it('no orb-overlay channel literal appears in main/ or preload/ sources — constants only', () => {
    // The failure this prevents already exists once: folder.clone maps to a
    // channel literally named 'git:clone', and a rename compiles clean on both
    // sides. ORB_OVERLAY_CHANNELS is the single source of channel names.
    const here = dirname(fileURLToPath(import.meta.url))
    const roots = [join(here, '..'), join(here, '..', '..', 'preload')]
    const sources = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) return sources(full)
        return entry.name.endsWith('.ts') && !entry.name.endsWith('.test.ts') ? [full] : []
      })
    const offenders = roots
      .flatMap(sources)
      .filter((file) => /["'`]orb-overlay:/.test(readFileSync(file, 'utf8')))
    expect(offenders).toEqual([])
  })
})

it('the structural slices accept the real electron shapes', () => {
  // Compile-time proof (tsc runs on this file): BrowserWindow and ipcMain
  // satisfy the wire's injected interfaces, so production wiring type-checks.
  const attach: (win: BrowserWindow, ipc: IpcMain) => OrbOverlayWire = attachOrbOverlayWire
  expect(attach).toBe(attachOrbOverlayWire)
})
