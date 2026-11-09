// SOLUSDEV-252 S3 test fixtures: a SolState, a circled region, and an
// in-memory SolBridge whose pushes the test drives by hand.
import { vi } from 'vitest'
import type { SolBridge } from '../../lib/desktopBridge'
import type {
  SolPillEvent,
  SolRegionPayload,
  SolState
} from '../../../../main/sol-window/solWindow'

export const SOL_STATE: SolState = {
  actionMode: 'guide',
  screenIntelligence: true,
  hotkeysEnabled: true,
  capture: { mode: 'available', message: '' },
  hotkeys: {
    hook: { status: 'available', message: '' },
    shortcuts: {},
    mode: 'hook',
    circleModeActive: false,
    summary: 'Hold Ctrl and circle to focus SOL on something'
  },
  lastRegionRefused: false
}

export const SOL_REGION: SolRegionPayload = {
  pngBase64: 'iVBORw0KGgoPIXELS=',
  contextPngBase64: 'iVBORw0KGgoCONTEXT=',
  width: 320,
  height: 200,
  source: { app: 'Onshape', title: 'Bracket v3' },
  capturedAt: 1
}

export interface FakeSolBridge extends SolBridge {
  /** Slice 3b; declared here until the preload SolBridge carries it. */
  openDriveApproval: () => Promise<void>
  pushState: (s: SolState) => void
  pushRegion: (r: SolRegionPayload) => void
  /** SOLUSDEV-319: drive main's pill motion cues (summoned / leaving). */
  pushPill: (e: SolPillEvent) => void
  /** SOLUSDEV-323: simulate main's hotkey-summon push. */
  pushSummoned: (at: number) => void
}

export function fakeSolBridge(state: SolState | null = SOL_STATE): FakeSolBridge {
  let stateHandler: ((s: SolState) => void) | null = null
  let regionHandler: ((r: SolRegionPayload) => void) | null = null
  let pillHandler: ((e: SolPillEvent) => void) | null = null
  let summonHandler: ((at: number) => void) | null = null
  return {
    getState: vi.fn(async () => state),
    setMode: vi.fn(async () => state),
    setScreenIntelligence: vi.fn(async () => state),
    setHotkeys: vi.fn(async () => state),
    open: vi.fn(async () => state),
    openCaptureSettings: vi.fn(async () => state),
    resize: vi.fn(async () => state),
    setBusy: vi.fn(async () => state),
    hide: vi.fn(async () => state),
    getDriveStatus: vi.fn(async () => null),
    setDrive: vi.fn(async () => null),
    requestDrivePermissions: vi.fn(async () => null),
    setDriving: vi.fn(async () => undefined),
    openDriveApproval: vi.fn(async () => undefined),
    onDriveStatus: vi.fn(() => () => undefined),
    onState: vi.fn((handler: (s: SolState) => void) => {
      stateHandler = handler
      return () => {
        stateHandler = null
      }
    }),
    onRegion: vi.fn((handler: (r: SolRegionPayload) => void) => {
      regionHandler = handler
      return () => {
        regionHandler = null
      }
    }),
    onPill: vi.fn((handler: (e: SolPillEvent) => void) => {
      pillHandler = handler
      return () => {
        pillHandler = null
      }
    }),
    onSummoned: vi.fn((handler: (at: number) => void) => {
      summonHandler = handler
      return () => {
        summonHandler = null
      }
    }),
    pushSummoned: (at) => summonHandler?.(at),
    pushState: (s) => stateHandler?.(s),
    pushPill: (e) => pillHandler?.(e),
    pushRegion: (r) => regionHandler?.(r)
  }
}

/** Install the fake as window.solus.sol (what getDesktopSolBridge reads). */
export function installSolBridge(bridge: FakeSolBridge): void {
  ;(window as unknown as { solus?: unknown }).solus = { sol: bridge }
}

export function uninstallSolBridge(): void {
  delete (window as unknown as { solus?: unknown }).solus
}
