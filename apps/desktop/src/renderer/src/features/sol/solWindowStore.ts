// SOLUSDEV-252 S3: the renderer's mirror of main's SOL state (`sol:state`
// pushes: sees-your-screen, gestures, capability messages) and the ONE
// circled region a gesture delivered (`sol:region`). Runtime-only, never
// persisted: the region is pixels, held in memory until the next send or a
// dismiss (docs/architecture/sol-window.md §6 "ephemeral by construction").
import { useEffect } from 'react'
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

/** SOLUSDEV-327: what every chat surface sends. SOL builds as needed — the server still cards
 *  destructive and unclassified actions (ADR action-mode amendment) — so no surface offers a
 *  Guide | Build switch. Only the plan's "Show me how instead" (one message) and the bench's
 *  "explain finding" (read-only by design) still ask for Guide. */
export const SOL_SEND_MODE: SolActionMode = 'do'

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
