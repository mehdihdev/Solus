// SOLUSDEV-223 (SOL-IPC-01) — the main-process end of the orb↔overlay push
// wire. CTR-06 defined the messages (packages/shared-types/src/orb-overlay.ts)
// but the app had no push-shaped IPC at all — every existing channel is
// invoke/handle. This module is the wire only: validated pushes to a window,
// validated subscriptions from it, and teardown bound to the window's
// lifetime. It holds no orb or overlay behaviour (SOLX-02 / LANE D attach it
// to their windows).
//
// Channel names come from ORB_OVERLAY_CHANNELS — never string literals; the
// ratchet in orbOverlayWire.test.ts keeps it that way. Both directions parse
// before acting: IPC crosses a process boundary and is untrusted input
// (CLAUDE.md §7). Electron is injected as structural slices so the logic is
// testable without a BrowserWindow (the companion.ts pattern).
//
// WHAT THIS WIRE DOES NOT GUARANTEE (security review, 2026-08-08): it
// authenticates the sending WINDOW (webContents id), nothing more. It does
// not know which handoffId is active, which project the session is scoped to,
// or whether a `reclaim`'s focus.projectId belongs to this user — that
// binding is the consumer's obligation (the SOLX-02 orb router / LANE D
// overlay host), enforced where the active handoff is known, with the
// cross-handoff isolation test living there. Likewise GuideStep text and
// `failed.reason` are shape-checked here but remain untrusted content: render
// them as text only, and wrap them as data before any prompt assembly.

import {
  ORB_OVERLAY_CHANNELS,
  parseOrbToOverlay,
  parseOverlayToOrb,
  type OrbToOverlay,
  type OverlayToOrb
} from '@solus/shared-types'

/** Structural slice of BrowserWindow — just what the wire needs. */
export interface WireWindow {
  isDestroyed(): boolean
  once(event: 'closed', listener: () => void): void
  off(event: 'closed', listener: () => void): void
  webContents: {
    id: number
    send(channel: string, message: unknown): void
  }
}

export interface WireIpcEvent {
  sender: { id: number }
}

/** Structural slice of ipcMain. */
export interface WireIpc {
  on(channel: string, listener: (event: WireIpcEvent, raw: unknown) => void): void
  removeListener(channel: string, listener: (event: WireIpcEvent, raw: unknown) => void): void
}

export type MalformedHandler = (channel: string, error: unknown) => void

// The contract's unknown-type error interpolates the sender's `type` field
// into its message; screen the field's size before parsing so a hostile
// megabyte string is refused without ever being copied into an Error.
const TYPE_CAP = 64
function screenType(raw: unknown): void {
  if (typeof raw === 'object' && raw !== null) {
    const t = (raw as Record<string, unknown>).type
    if (typeof t === 'string' && t.length > TYPE_CAP) {
      throw new TypeError('type: exceeds the message-type cap')
    }
  }
}

// Default malformed-message logger: control characters stripped (a hostile
// payload must not forge log lines), detail capped, and at most
// MALFORMED_LOG_CAP reports per channel per wire (a flood must not amplify
// into unbounded logging). State is per-wire via the default-argument call.
const MALFORMED_LOG_CAP = 5
function defaultMalformedLogger(): MalformedHandler {
  const counts = new Map<string, number>()
  return (channel, error) => {
    const n = (counts.get(channel) ?? 0) + 1
    counts.set(channel, n)
    if (n > MALFORMED_LOG_CAP) return
    const detail =
      error instanceof Error ? error.message.replace(/\p{Cc}/gu, ' ').slice(0, 200) : 'unparseable'
    const suffix = n === MALFORMED_LOG_CAP ? ' (suppressing further reports on this channel)' : ''
    console.error(`[orb-overlay] dropped malformed message on ${channel}: ${detail}${suffix}`)
  }
}

export interface OrbOverlayWire {
  /** Push a validated overlay→orb message to this window; false once it is gone. */
  pushToOrb(message: OverlayToOrb): boolean
  /** Push a validated orb→overlay message to this window; false once it is gone. */
  pushToOverlay(message: OrbToOverlay): boolean
  /** Hear validated orb→overlay messages from THIS window only; returns unsubscribe. */
  onOrbToOverlay(handler: (message: OrbToOverlay) => void): () => void
  /** Hear validated overlay→orb messages from THIS window only; returns unsubscribe. */
  onOverlayToOrb(handler: (message: OverlayToOrb) => void): () => void
  /** Remove every listener; idempotent. Runs automatically when the window closes. */
  detach(): void
}

/**
 * Bind the push wire to one window — one wire per window; a second wire on
 * the same window double-delivers every message. Outbound messages are parsed
 * before they cross (a malformed one throws — that is a bug in our own
 * process, not untrusted input); inbound messages are parsed and dropped via
 * `onMalformed` when they fail. Every subscription dies with the window: a
 * listener surviving its BrowserWindow is a leak and a crash after `dismiss`.
 */
export function attachOrbOverlayWire(
  win: WireWindow,
  ipc: WireIpc,
  onMalformed: MalformedHandler = defaultMalformedLogger()
): OrbOverlayWire {
  interface Registered {
    channel: string
    listener: (event: WireIpcEvent, raw: unknown) => void
  }
  const registered = new Set<Registered>()
  // Captured once: the inbound filter must not touch win.webContents later —
  // after a renderer crash the window outlives its webContents, and property
  // access on a destroyed WebContents throws inside the ipcMain listener.
  const senderId = win.webContents.id
  let detached = false

  const push = (channel: string, parsed: unknown): boolean => {
    if (detached || win.isDestroyed()) return false
    win.webContents.send(channel, parsed)
    return true
  }

  const subscribe = <M>(
    channel: string,
    parse: (raw: unknown) => M,
    handler: (message: M) => void
  ): (() => void) => {
    if (detached) throw new Error('orb-overlay wire: window already closed')
    const listener = (event: WireIpcEvent, raw: unknown): void => {
      // ipcMain listeners are process-global; this wire only speaks for its
      // window. Filtering on the top-level webContents id is sound while the
      // renderer CSP stays default-src 'self' (no foreign frames can run in
      // this window); if frame-src or <webview> ever widens, revisit with a
      // senderFrame === mainFrame check.
      if (event.sender.id !== senderId) return
      let message: M
      try {
        screenType(raw)
        message = parse(raw)
      } catch (error: unknown) {
        onMalformed(channel, error)
        return
      }
      handler(message)
    }
    const entry: Registered = { channel, listener }
    registered.add(entry)
    ipc.on(channel, listener)
    return () => {
      if (registered.delete(entry)) ipc.removeListener(channel, listener)
    }
  }

  const wire: OrbOverlayWire = {
    pushToOrb: (message) => push(ORB_OVERLAY_CHANNELS.toOrb, parseOverlayToOrb(message)),
    pushToOverlay: (message) => push(ORB_OVERLAY_CHANNELS.toOverlay, parseOrbToOverlay(message)),
    onOrbToOverlay: (handler) =>
      subscribe(ORB_OVERLAY_CHANNELS.toOverlay, parseOrbToOverlay, handler),
    onOverlayToOrb: (handler) => subscribe(ORB_OVERLAY_CHANNELS.toOrb, parseOverlayToOrb, handler),
    detach: () => {
      detached = true
      win.off('closed', onClosed)
      for (const { channel, listener } of registered) ipc.removeListener(channel, listener)
      registered.clear()
    }
  }
  const onClosed = (): void => wire.detach()
  if (win.isDestroyed()) {
    // Attached to a window that already died: never register anything.
    detached = true
  } else {
    win.once('closed', onClosed)
  }
  return wire
}
