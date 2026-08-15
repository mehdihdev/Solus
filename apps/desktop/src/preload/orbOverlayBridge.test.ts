// SOLUSDEV-223 (SOL-IPC-01) — the renderer-facing end of the orb↔overlay push
// wire. Pure factory over an injected ipcRenderer, so the parse-before-send /
// parse-before-deliver behaviour is provable without Electron.
import { describe, it, expect, vi } from 'vitest'
import type { IpcRenderer } from 'electron'
import { ORB_OVERLAY_CHANNELS, type OrbToOverlay, type OverlayToOrb } from '@solus/shared-types'
import { createOrbOverlayBridge, type BridgeIpc, type OrbOverlayBridge } from './orbOverlayBridge'

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
const MALFORMED = { type: 'advance', handoffId: 'h-1', step: null }

type Listener = (event: unknown, raw: unknown) => void

function fakeIpcRenderer(): {
  ipc: BridgeIpc
  sent: Array<{ channel: string; message: unknown }>
  emit: (channel: string, raw: unknown) => void
  count: (channel: string) => number
} {
  const sent: Array<{ channel: string; message: unknown }> = []
  const listeners = new Map<string, Set<Listener>>()
  return {
    ipc: {
      send: (channel, message) => {
        sent.push({ channel, message })
      },
      on: (channel, listener) => {
        const set = listeners.get(channel) ?? new Set()
        set.add(listener)
        listeners.set(channel, set)
      },
      removeListener: (channel, listener) => {
        listeners.get(channel)?.delete(listener)
      }
    },
    sent,
    emit: (channel, raw) => {
      for (const listener of [...(listeners.get(channel) ?? [])]) listener({}, raw)
    },
    count: (channel) => listeners.get(channel)?.size ?? 0
  }
}

describe('publish', () => {
  it('publishToOverlay validates then sends a fresh parsed message on the toOverlay channel', () => {
    const f = fakeIpcRenderer()
    const bridge = createOrbOverlayBridge(f.ipc)
    bridge.publishToOverlay(ADVANCE)
    expect(f.sent).toHaveLength(1)
    expect(f.sent[0].channel).toBe(ORB_OVERLAY_CHANNELS.toOverlay)
    expect(f.sent[0].message).toEqual(ADVANCE)
    expect(f.sent[0].message).not.toBe(ADVANCE)
  })

  it('publishToOrb (the overlay side) sends on the toOrb channel', () => {
    const f = fakeIpcRenderer()
    createOrbOverlayBridge(f.ipc).publishToOrb(READY)
    expect(f.sent[0].channel).toBe(ORB_OVERLAY_CHANNELS.toOrb)
    expect(f.sent[0].message).toEqual(READY)
  })

  it('a malformed publish throws and nothing is sent', () => {
    const f = fakeIpcRenderer()
    const bridge = createOrbOverlayBridge(f.ipc)
    expect(() => bridge.publishToOverlay(MALFORMED as unknown as OrbToOverlay)).toThrow(TypeError)
    expect(f.sent).toHaveLength(0)
  })
})

describe('subscribe', () => {
  it('delivers a valid inbound message, parsed', () => {
    const f = fakeIpcRenderer()
    const bridge = createOrbOverlayBridge(f.ipc)
    const seen: OverlayToOrb[] = []
    bridge.onOverlayToOrb((m) => seen.push(m))
    f.emit(ORB_OVERLAY_CHANNELS.toOrb, READY)
    expect(seen).toEqual([READY])
    expect(seen[0]).not.toBe(READY)
  })

  it('rejects a malformed inbound message at the boundary: handler never runs', () => {
    const f = fakeIpcRenderer()
    const onMalformed = vi.fn()
    const bridge = createOrbOverlayBridge(f.ipc, onMalformed)
    const handler = vi.fn()
    bridge.onOrbToOverlay(handler)
    f.emit(ORB_OVERLAY_CHANNELS.toOverlay, MALFORMED)
    f.emit(ORB_OVERLAY_CHANNELS.toOverlay, 42)
    expect(handler).not.toHaveBeenCalled()
    expect(onMalformed).toHaveBeenCalledTimes(2)
    expect(onMalformed).toHaveBeenCalledWith(ORB_OVERLAY_CHANNELS.toOverlay, expect.any(TypeError))
  })

  it('screens a hostile megabyte `type` field before it can bloat an error message', () => {
    const f = fakeIpcRenderer()
    const onMalformed = vi.fn()
    const bridge = createOrbOverlayBridge(f.ipc, onMalformed)
    const handler = vi.fn()
    bridge.onOverlayToOrb(handler)
    f.emit(ORB_OVERLAY_CHANNELS.toOrb, { type: 'A'.repeat(1_000_000), handoffId: 'h-1' })
    expect(handler).not.toHaveBeenCalled()
    expect(onMalformed).toHaveBeenCalledTimes(1)
    const error = onMalformed.mock.calls[0][1] as Error
    expect(error.message.length).toBeLessThan(256)
  })

  it('the default logger strips control characters (no forged console lines)', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const f = fakeIpcRenderer()
      const bridge = createOrbOverlayBridge(f.ipc)
      bridge.onOrbToOverlay(vi.fn())
      f.emit(ORB_OVERLAY_CHANNELS.toOverlay, { type: 'x\nFORGED ENTRY', handoffId: 'h-1' })
      expect(spy).toHaveBeenCalledTimes(1)
      expect(spy.mock.calls[0].join(' ')).not.toMatch(/[\n\r]/)
    } finally {
      spy.mockRestore()
    }
  })

  it('unsubscribe removes the listener (component-lifecycle cleanup)', () => {
    const f = fakeIpcRenderer()
    const bridge = createOrbOverlayBridge(f.ipc)
    const handler = vi.fn()
    const unsubscribe = bridge.onOverlayToOrb(handler)
    expect(f.count(ORB_OVERLAY_CHANNELS.toOrb)).toBe(1)
    unsubscribe()
    expect(f.count(ORB_OVERLAY_CHANNELS.toOrb)).toBe(0)
    f.emit(ORB_OVERLAY_CHANNELS.toOrb, READY)
    expect(handler).not.toHaveBeenCalled()
  })
})

it('the structural slice accepts the real ipcRenderer shape', () => {
  // Compile-time proof (tsc runs on this file): Electron's IpcRenderer
  // satisfies BridgeIpc, so preload/index.ts's binding type-checks.
  const create: (ipc: IpcRenderer) => OrbOverlayBridge = createOrbOverlayBridge
  expect(create).toBe(createOrbOverlayBridge)
})
