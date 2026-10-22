import type { ToolWindowRef } from '@solus/shared-types'
// SOLUSDEV-252 S3: the renderer end of the SOL window surface, exposed as
// window.solus.sol (docs/architecture/sol-window.md §2). A pure factory over an
// injected ipcRenderer so the validate-before-deliver behaviour is testable;
// preload/index.ts binds the real one. Channel names come from
// SOL_WINDOW_CHANNELS only (the ratchet in main/sol-window/solWindow.test.ts).
import { SOL_WINDOW_CHANNELS } from '../main/sol-window/solWindow.constants'
import type { SolRegionPayload, SolState } from '../main/sol-window/solWindow'
import type { SolActionMode } from '../main/solSettings'

/** Structural slice of ipcRenderer — just what the bridge needs. */
export interface SolBridgeIpc {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>
  on(channel: string, listener: (event: unknown, raw: unknown) => void): void
  removeListener(channel: string, listener: (event: unknown, raw: unknown) => void): void
}

export interface SolBridge {
  getGuideTarget?(): Promise<ToolWindowRef | null>
  getState(): Promise<SolState | null>
  setMode(mode: SolActionMode): Promise<SolState | null>
  setScreenIntelligence(on: boolean): Promise<SolState | null>
  /** The hold-Ctrl gestures (native key hook + cursor sampler) on/off. */
  setHotkeys(on: boolean): Promise<SolState | null>
  setAlwaysOnTop(on: boolean): Promise<SolState | null>
  /** Open (or focus) the SOL window. */
  open(): Promise<SolState | null>
  /** Open the OS pane that grants screen capture (macOS Screen Recording). */
  openCaptureSettings(): Promise<SolState | null>
  onState(handler: (state: SolState) => void): () => void
  onRegion(handler: (region: SolRegionPayload) => void): () => void
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const isCapability = (v: unknown): boolean =>
  isRecord(v) && typeof v.mode === 'string' && typeof v.message === 'string'

const FLAG_KEYS = ['screenIntelligence', 'hotkeysEnabled', 'alwaysOnTop', 'lastRegionRefused']
const hasFlags = (r: Record<string, unknown>): boolean =>
  FLAG_KEYS.every((k) => typeof r[k] === 'boolean')

export function isSolState(raw: unknown): raw is SolState {
  if (!isRecord(raw)) return false
  return (
    (raw.actionMode === 'guide' || raw.actionMode === 'do') &&
    hasFlags(raw) &&
    isCapability(raw.capture) &&
    (raw.hotkeys === null || isRecord(raw.hotkeys))
  )
}

export function isSolRegion(raw: unknown): raw is SolRegionPayload {
  if (!isRecord(raw)) return false
  const source = raw.source
  return (
    typeof raw.pngBase64 === 'string' &&
    typeof raw.contextPngBase64 === 'string' &&
    typeof raw.width === 'number' &&
    typeof raw.height === 'number' &&
    typeof raw.capturedAt === 'number' &&
    (source === null ||
      (isRecord(source) && typeof source.app === 'string' && typeof source.title === 'string'))
  )
}

function isGuideTarget(raw: unknown): raw is ToolWindowRef {
  if (
    !isRecord(raw) ||
    raw.tool !== 'kicad' ||
    typeof raw.windowTitle !== 'string' ||
    raw.windowTitle.length > 256 ||
    !(raw.displayId === null || typeof raw.displayId === 'string') ||
    !isRecord(raw.bounds)
  )
    return false
  return validGuideBounds(raw.bounds)
}

export function createSolBridge(ipc: SolBridgeIpc): SolBridge {
  const call = (channel: string, ...args: unknown[]): Promise<SolState | null> =>
    ipc.invoke(channel, ...args).then((raw) => (isSolState(raw) ? raw : null))
  const subscribe = <M>(
    channel: string,
    accept: (raw: unknown) => raw is M,
    handler: (message: M) => void
  ): (() => void) => {
    const listener = (_event: unknown, raw: unknown): void => {
      // Malformed pushes are dropped here; only the channel is echoed, never the payload.
      if (accept(raw)) handler(raw)
      else console.error(`[sol] dropped malformed message on ${channel}`)
    }
    ipc.on(channel, listener)
    return () => ipc.removeListener(channel, listener)
  }
  const c = SOL_WINDOW_CHANNELS
  return {
    getGuideTarget: () =>
      ipc.invoke(c.guideTarget).then((raw) => (isGuideTarget(raw) ? raw : null)),
    getState: () => call(c.getState),
    setMode: (mode) => call(c.setMode, mode),
    setScreenIntelligence: (on) => call(c.setScreenIntelligence, on),
    setHotkeys: (on) => call(c.setHotkeys, on),
    setAlwaysOnTop: (on) => call(c.setAlwaysOnTop, on),
    open: () => call(c.open),
    openCaptureSettings: () => call(c.openCaptureSettings),
    onState: (handler) => subscribe(c.state, isSolState, handler),
    onRegion: (handler) => subscribe(c.region, isSolRegion, handler)
  }
}

function validGuideBounds(b: Record<string, unknown>): boolean {
  return (
    [b.x, b.y, b.width, b.height].every(Number.isSafeInteger) &&
    typeof b.width === 'number' &&
    typeof b.height === 'number' &&
    b.width > 0 &&
    b.height > 0 &&
    b.width <= 16384 &&
    b.height <= 16384
  )
}
