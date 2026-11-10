import type { ToolWindowRef } from '@solus/shared-types'
// SOLUSDEV-252 S3: the renderer end of the SOL window surface, exposed as
// window.solus.sol (docs/architecture/sol-window.md §2). A pure factory over an
// injected ipcRenderer so the validate-before-deliver behaviour is testable;
// preload/index.ts binds the real one. Channel names come from
// SOL_WINDOW_CHANNELS only (the ratchet in main/sol-window/solWindow.test.ts).
import { SOL_WINDOW_CHANNELS } from '../main/sol-window/solWindow.constants'
import type { SolPillEvent, SolRegionPayload, SolState } from '../main/sol-window/solWindow'
import type { SolActionMode } from '../main/solSettings'
import { DRIVE_AGENT_STATES, DRIVE_UNAVAILABLE, type DriveStatus } from '../main/drive/driveStatus'
import { isSolFrontApp, type SolFrontApp } from '../main/drive/frontAppShape'
import type { SolScreenPayload } from '../main/capture/summonShot'

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
  /** Open (or focus) the SOL window. */
  open(): Promise<SolState | null>
  /** Open the OS pane that grants screen capture (macOS Screen Recording). */
  openCaptureSettings(): Promise<SolState | null>
  /** SOLUSDEV-319: the pill's measured content height; main grows it upward. */
  resize(height: number): Promise<SolState | null>
  /** SOLUSDEV-319: while busy the pill does not hide on blur. */
  setBusy(busy: boolean): Promise<SolState | null>
  /** SOLUSDEV-319: hide the pill (Esc); its window and thread live on. */
  hide(): Promise<SolState | null>
  /** SOLUSDEV-319 drive slice 3 (sol-drive.md §5). */
  getDriveStatus(): Promise<DriveStatus | null>
  setDrive(on: boolean): Promise<DriveStatus | null>
  /** Runs the helper's `trust --prompt`; resolves with the refreshed status. */
  requestDrivePermissions(): Promise<DriveStatus | null>
  /** The renderer says a drive.step is running (true) or ended (false). */
  setDriving(active: boolean): Promise<void>
  /** Slice 3b: open System Settings › Login Items so the user can approve the agent. */
  openDriveApproval(): Promise<void>
  onDriveStatus(handler: (status: DriveStatus) => void): () => void
  onState(handler: (state: SolState) => void): () => void
  onRegion(handler: (region: SolRegionPayload) => void): () => void
  /** SOLUSDEV-319: the pill's motion cues (summoned / leaving) — SOL window only. */
  onPill?(handler: (event: SolPillEvent) => void): () => void
  /** SOLUSDEV-319 slice 4 (sol-drive.md §2.2): the front-app summon snapshot —
   *  SOL window only; null when none (drive off, cleared, nothing in front). */
  onFrontApp?(handler: (front: SolFrontApp | null) => void): () => void
  /** SOLUSDEV-323: a hotkey summon happened (epoch ms). */
  onSummoned(handler: (at: number) => void): () => void
  /** SOLUSDEV-324: the picture main took at summon — once; null when none,
   *  when not asked from the pill, or on any failure. */
  takeScreen?(): Promise<SolScreenPayload | null>
}

const isFrontAppPush = (raw: unknown): raw is SolFrontApp | null =>
  raw === null || isSolFrontApp(raw)

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const isCapability = (v: unknown): boolean =>
  isRecord(v) && typeof v.mode === 'string' && typeof v.message === 'string'

const FLAG_KEYS = ['screenIntelligence', 'hotkeysEnabled', 'lastRegionRefused']
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

const isTrust = (v: unknown): boolean =>
  v === null ||
  (isRecord(v) && typeof v.accessibility === 'boolean' && typeof v.screenRecording === 'boolean')

/** `reason` is null exactly when `available` (driveStatus.ts). */
export function isDriveStatus(raw: unknown): raw is DriveStatus {
  if (!isRecord(raw) || typeof raw.available !== 'boolean') return false
  const reasonOk = raw.available
    ? raw.reason === null
    : (DRIVE_UNAVAILABLE as readonly unknown[]).includes(raw.reason)
  return (
    reasonOk &&
    typeof raw.enabled === 'boolean' &&
    typeof raw.unsignedDev === 'boolean' &&
    isTrust(raw.trust) &&
    (raw.agent === null || (DRIVE_AGENT_STATES as readonly unknown[]).includes(raw.agent))
  )
}

const isSummoned = (raw: unknown): raw is { at: number } =>
  isRecord(raw) && typeof raw.at === 'number' && Number.isFinite(raw.at)

const isSource = (source: unknown): boolean =>
  source === null ||
  (isRecord(source) && typeof source.app === 'string' && typeof source.title === 'string')

const hasSize = (raw: Record<string, unknown>): boolean =>
  typeof raw.width === 'number' &&
  typeof raw.height === 'number' &&
  typeof raw.capturedAt === 'number'

export function isSolRegion(raw: unknown): raw is SolRegionPayload {
  if (!isRecord(raw)) return false
  return (
    typeof raw.pngBase64 === 'string' &&
    typeof raw.contextPngBase64 === 'string' &&
    hasSize(raw) &&
    isSource(raw.source)
  )
}

export function isSolScreen(raw: unknown): raw is SolScreenPayload {
  return (
    isRecord(raw) && typeof raw.jpegBase64 === 'string' && hasSize(raw) && isSource(raw.source)
  )
}

export function isSolPillEvent(raw: unknown): raw is SolPillEvent {
  if (!isRecord(raw)) return false
  return raw.kind === 'leaving' || (raw.kind === 'summoned' && typeof raw.resume === 'boolean')
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
  const callDrive = (channel: string, ...args: unknown[]): Promise<DriveStatus | null> =>
    ipc.invoke(channel, ...args).then((raw) => (isDriveStatus(raw) ? raw : null))
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
    open: () => call(c.open),
    openCaptureSettings: () => call(c.openCaptureSettings),
    resize: (height) => call(c.resize, height),
    setBusy: (busy) => call(c.setBusy, busy),
    hide: () => call(c.hide),
    getDriveStatus: () => callDrive(c.getDriveStatus),
    setDrive: (on) => callDrive(c.setDrive, on),
    requestDrivePermissions: () => callDrive(c.requestDrivePermissions),
    setDriving: (active) => ipc.invoke(c.setDriving, active).then(() => undefined),
    openDriveApproval: () => ipc.invoke(c.openDriveApproval).then(() => undefined),
    onDriveStatus: (handler) => subscribe(c.driveStatus, isDriveStatus, handler),
    onState: (handler) => subscribe(c.state, isSolState, handler),
    onRegion: (handler) => subscribe(c.region, isSolRegion, handler),
    onPill: (handler) => subscribe(c.pill, isSolPillEvent, handler),
    onFrontApp: (handler) => subscribe(c.frontApp, isFrontAppPush, handler),
    onSummoned: (handler) => subscribe(c.summoned, isSummoned, (m) => handler(m.at)),
    takeScreen: () =>
      ipc.invoke(c.takeScreen).then(
        (raw) => (isSolScreen(raw) ? raw : null),
        () => null
      )
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
