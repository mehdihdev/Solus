// SOLUSDEV-252 S3: the renderer's mirror of main's SOL state (`sol:state`
// pushes: action mode, sees-your-screen, pin, capability messages) and the ONE
// circled region a gesture delivered (`sol:region`). Runtime-only, never
// persisted: the region is pixels, held in memory until the next send or a
// dismiss (docs/architecture/sol-window.md §6 "ephemeral by construction").
import { useEffect, useState } from 'react'
import { create } from 'zustand'
import { getDesktopSolBridge, type SolBridge } from '../../lib/desktopBridge'
import type { SolRegionPayload, SolState } from '../../../../main/sol-window/solWindow'
import type { SolFrontApp } from '../../../../main/drive/frontAppShape'
import type { SolScreenPayload } from '../../../../main/capture/summonShot'
import type { SolActionMode, SolScreenshot } from './solApi'
import { onAccountEnd } from './solSessionStore'

export interface SolWindowState {
  state: SolState | null
  region: SolRegionPayload | null
  setState: (state: SolState) => void
  setRegion: (region: SolRegionPayload) => void
  clearRegion: () => void
  /** SOLUSDEV-319: one plan runs at a time across the surface; the pill is busy meanwhile. */
  planRunning: boolean
  setPlanRunning: (running: boolean) => void
  /** SOLUSDEV-319 slice 4: main's front-app summon snapshot — set only while
   *  the pill is mounted (useFrontAppSnapshot); null elsewhere and when none. */
  frontApp: SolFrontApp | null
  setFrontApp: (front: SolFrontApp | null) => void
}

export const useSolWindowStore = create<SolWindowState>()((set) => ({
  state: null,
  region: null,
  setState: (state) => set({ state }),
  setRegion: (region) => set({ region }),
  clearRegion: () => set({ region: null }),
  planRunning: false,
  setPlanRunning: (planRunning) => set({ planRunning }),
  frontApp: null,
  setFrontApp: (frontApp) => set({ frontApp })
}))

// FIX-2-R H1: the region is the signed-in account's pixels — sign-out or an
// identity swap drops it (a project switch does too, via projectSwitch.ts).
onAccountEnd(() => useSolWindowStore.setState({ region: null, frontApp: null }))

let disconnect: (() => void) | null = null

/** Subscribe this renderer to main's pushes and ask for the current state.
 *  Idempotent. The first getState() is what tells main the SOL window is
 *  mounted (markReady) and flushes a region queued before the renderer was up. */
export function connectSolBridge(bridge: SolBridge | null = getDesktopSolBridge()): void {
  if (disconnect !== null || bridge === null) return
  const { setState, setRegion } = useSolWindowStore.getState()
  const offState = bridge.onState(setState)
  const offRegion = bridge.onRegion(setRegion)
  disconnect = () => {
    offState()
    offRegion()
  }
  void bridge.getState().then((state) => {
    if (state) setState(state)
  })
}

export function disconnectSolBridge(): void {
  disconnect?.()
  disconnect = null
}

/** SOLUSDEV-319 slice 4: the pill (and only the pill) mirrors main's
 *  front-app snapshot while mounted; unmounting unsubscribes and forgets it.
 *  A bridge without onFrontApp (older preload, browser) leaves it null. */
export function useFrontAppSnapshot(
  bridge: Pick<SolBridge, 'onFrontApp'> | null = getDesktopSolBridge()
): void {
  useEffect(() => {
    const { setFrontApp } = useSolWindowStore.getState()
    const off = bridge?.onFrontApp?.(setFrontApp)
    return () => {
      off?.()
      setFrontApp(null)
    }
  }, [bridge])
}

/** UI labels for the SOLX-01 axis: Guide | Build (sol-window.md §7). */
export const MODE_LABEL: Record<SolActionMode, 'Guide' | 'Build'> = { guide: 'Guide', do: 'Build' }
export const oppositeMode = (mode: SolActionMode): SolActionMode =>
  mode === 'guide' ? 'do' : 'guide'

// The composer opens in Do outside Electron, not Guide. Guide refuses exactly
// the tools whose descriptor sets `requires_confirmation` (agent/modes.py) —
// precisely the set the CTR-03 confirmation gate already parks, so a Guide
// default bought no safety. Inside Electron the shared setting wins.
const LOCAL_DEFAULT_ACTION_MODE: SolActionMode = 'do'

/** The SHARED action mode: main's setting when the bridge is present (every
 *  renderer sees the same value; Ctrl+Space, the tray and every badge agree),
 *  otherwise a local per-surface state. */
export function useSolActionMode(): {
  mode: SolActionMode
  setMode: (mode: SolActionMode) => void
} {
  const shared = useSolWindowStore((s) => s.state?.actionMode ?? null)
  const [local, setLocal] = useState<SolActionMode>(LOCAL_DEFAULT_ACTION_MODE)
  useEffect(() => connectSolBridge(), [])
  const bridge = getDesktopSolBridge()
  const setMode = (mode: SolActionMode): void => {
    if (bridge && shared !== null) void bridge.setMode(mode)
    else setLocal(mode)
  }
  return { mode: shared ?? local, setMode }
}

/** The API's `ScreenshotSource` caps (agent/screen.py) — a long window title
 *  must never 422 the turn and lose the capture (FIX-2-R M3). */
const SOURCE_APP_MAX = 128
const SOURCE_TITLE_MAX = 256

const capSource = (source: SolRegionPayload['source']): SolScreenshot['source'] =>
  source && {
    app: source.app.slice(0, SOURCE_APP_MAX),
    title: source.title.slice(0, SOURCE_TITLE_MAX)
  }

/** The attached region as the turn's `screenshot` body (sol-window.md §8). */
export function regionToScreenshot(region: SolRegionPayload): SolScreenshot {
  return {
    media_type: 'image/png',
    data: region.pngBase64,
    width: region.width,
    height: region.height,
    source: capSource(region.source),
    context: region.contextPngBase64
  }
}

/** SOLUSDEV-324: the summon picture as the turn's `screenshot` — the whole
 *  screen is already the context, so none rides separately. */
export function screenToScreenshot(shot: SolScreenPayload): SolScreenshot {
  return {
    media_type: 'image/jpeg',
    data: shot.jpegBase64,
    width: shot.width,
    height: shot.height,
    source: capSource(shot.source),
    context: null
  }
}

/** SOLUSDEV-324: with "SOL sees your screen" on, the picture main took at
 *  summon (once). Null when off, outside the pill, or on any failure — a turn
 *  is never lost to the picture. */
export async function takeSummonScreenshot(
  bridge: Pick<SolBridge, 'takeScreen'> | null = getDesktopSolBridge()
): Promise<SolScreenshot | undefined> {
  if (!useSolWindowStore.getState().state?.screenIntelligence || !bridge?.takeScreen) return
  const shot = await bridge.takeScreen().catch(() => null)
  return shot ? screenToScreenshot(shot) : undefined
}
