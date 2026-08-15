// SOLUSDEV-223 (SOL-IPC-01) — the renderer-facing end of the orb↔overlay push
// wire, exposed on window.solus.orbOverlay (window.api is vestigial — nothing
// is added to it). A pure factory over an injected ipcRenderer so the
// parse-before-send / parse-before-deliver behaviour is unit-testable;
// preload/index.ts binds the real ipcRenderer.
//
// Channel names come from ORB_OVERLAY_CHANNELS — never string literals (the
// ratchet in main/sol-window/orbOverlayWire.test.ts scans this directory too).
// Renderer-side listeners die with their window, so unsubscribe here is for
// component-lifecycle cleanup (React effect teardown), not leak prevention.

import {
  ORB_OVERLAY_CHANNELS,
  parseOrbToOverlay,
  parseOverlayToOrb,
  type OrbToOverlay,
  type OverlayToOrb
} from '@solus/shared-types'

/** Structural slice of ipcRenderer — just what the bridge needs. */
export interface BridgeIpc {
  send(channel: string, message: unknown): void
  on(channel: string, listener: (event: unknown, raw: unknown) => void): void
  removeListener(channel: string, listener: (event: unknown, raw: unknown) => void): void
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

// Control characters stripped (a hostile payload must not forge console
// lines) and detail capped before anything is echoed.
const logMalformed: MalformedHandler = (channel, error) => {
  const detail =
    error instanceof Error ? error.message.replace(/\p{Cc}/gu, ' ').slice(0, 200) : 'unparseable'
  console.error(`[orb-overlay] dropped malformed message on ${channel}: ${detail}`)
}

export interface OrbOverlayBridge {
  /** Orb side: send to the overlay; a malformed message throws (caller bug). */
  publishToOverlay(message: OrbToOverlay): void
  /** Orb side: hear the overlay; malformed inbound is dropped at the boundary. */
  onOverlayToOrb(handler: (message: OverlayToOrb) => void): () => void
  /** Overlay side (LANE D's window): the mirror of publishToOverlay. */
  publishToOrb(message: OverlayToOrb): void
  /** Overlay side (LANE D's window): the mirror of onOverlayToOrb. */
  onOrbToOverlay(handler: (message: OrbToOverlay) => void): () => void
}

export function createOrbOverlayBridge(
  ipc: BridgeIpc,
  onMalformed: MalformedHandler = logMalformed
): OrbOverlayBridge {
  const subscribe = <M>(
    channel: string,
    parse: (raw: unknown) => M,
    handler: (message: M) => void
  ): (() => void) => {
    const listener = (_event: unknown, raw: unknown): void => {
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
    ipc.on(channel, listener)
    return () => ipc.removeListener(channel, listener)
  }

  return {
    publishToOverlay: (message) =>
      ipc.send(ORB_OVERLAY_CHANNELS.toOverlay, parseOrbToOverlay(message)),
    onOverlayToOrb: (handler) => subscribe(ORB_OVERLAY_CHANNELS.toOrb, parseOverlayToOrb, handler),
    publishToOrb: (message) => ipc.send(ORB_OVERLAY_CHANNELS.toOrb, parseOverlayToOrb(message)),
    onOrbToOverlay: (handler) =>
      subscribe(ORB_OVERLAY_CHANNELS.toOverlay, parseOrbToOverlay, handler)
  }
}
