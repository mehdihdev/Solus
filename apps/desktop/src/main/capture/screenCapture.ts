// SOLUSDEV-252 S3: the ONE screen-capture interface (docs/architecture/
// sol-window.md §6) over `desktopCapturer`. Per-OS permission probes come from
// platform/capabilities; every failure is a CaptureUnavailable VALUE — callers
// never see a throw. Captures are ephemeral: buffers live for one turn and are
// never written to disk or logged (§6 "ephemeral by construction", §9).
import { desktopCapturer, screen, systemPreferences } from 'electron'
import { staticCapabilities, type PlatformBasics } from '../platform/capabilities'
import { activeWindow, realActiveWindowDeps, type ActiveWindowInfo } from './activeWindow'

/** Downscaled full-screen context image width cap (§6). */
export const CONTEXT_MAX_WIDTH = 1280

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

export interface CaptureCapability {
  mode: 'available' | 'needs-permission' | 'unavailable'
  message: string
  settingsUrl?: string
}

export interface CaptureResult {
  /** PNG of the region (physical pixels). */
  png: Buffer
  /** PNG of the whole display, ≤ CONTEXT_MAX_WIDTH wide. */
  contextPng: Buffer
  width: number
  height: number
  scale: number
  display: number
  context: { crop: Rect; screen: Rect }
  window: ActiveWindowInfo | null
}

export interface CaptureUnavailable {
  reason: 'disabled' | 'needs-permission' | 'unavailable' | 'empty-region' | 'error'
  message: string
  settingsUrl?: string
}

export interface ScreenCapture {
  capability(): CaptureCapability
  captureRegion(region: Rect): Promise<CaptureResult | CaptureUnavailable>
}

/** Structural slice of Electron's NativeImage. */
export interface CaptureImage {
  getSize(): { width: number; height: number }
  crop(rect: Rect): CaptureImage
  resize(options: { width: number }): CaptureImage
  toPNG(): Buffer
}

export interface CaptureDisplay {
  id: number
  /** DIP bounds in screen coordinates. */
  bounds: Rect
  scaleFactor: number
}

export interface ScreenCaptureDeps {
  basics: PlatformBasics
  getSources(options: {
    types: ['screen']
    thumbnailSize: { width: number; height: number }
  }): Promise<Array<{ id: string; display_id: string; thumbnail: CaptureImage }>>
  getDisplayNearestPoint(point: { x: number; y: number }): CaptureDisplay
  /** darwin only: systemPreferences.getMediaAccessStatus('screen'). */
  getMediaAccessStatus?: (mediaType: 'screen') => string
  /** The "SOL sees your screen" setting. False → no capture, ever, before any
   *  permission or source work (§7) — the one gate every caller routes through. */
  isEnabled?: () => boolean
  activeWindow(): Promise<ActiveWindowInfo | null>
  warn(message: string): void
}

function intersect(a: Rect, b: Rect): Rect {
  const x = Math.max(a.x, b.x)
  const y = Math.max(a.y, b.y)
  return {
    x,
    y,
    width: Math.min(a.x + a.width, b.x + b.width) - x,
    height: Math.min(a.y + a.height, b.y + b.height) - y
  }
}

/** The display's screen source → the crop and the downscaled context image. */
async function grab(
  deps: ScreenCaptureDeps,
  display: CaptureDisplay,
  crop: Rect
): Promise<CaptureResult | CaptureUnavailable> {
  const sources = await deps.getSources({
    types: ['screen'],
    thumbnailSize: {
      width: Math.round(display.bounds.width * display.scaleFactor),
      height: Math.round(display.bounds.height * display.scaleFactor)
    }
  })
  const source = sources.find((s) => s.display_id === String(display.id)) ?? sources[0]
  if (!source) return { reason: 'error', message: 'No screen source was available.' }
  const thumb = source.thumbnail
  // The capturer may hand back a thumbnail scaled to fit, so derive the
  // DIP→pixel ratio from what we actually got rather than trusting scaleFactor.
  const scale = thumb.getSize().width / display.bounds.width
  const px = (n: number): number => Math.round(n * scale)
  const pixelCrop = {
    x: px(crop.x - display.bounds.x),
    y: px(crop.y - display.bounds.y),
    width: Math.max(1, px(crop.width)),
    height: Math.max(1, px(crop.height))
  }
  const cropped = thumb.crop(pixelCrop)
  const context =
    thumb.getSize().width > CONTEXT_MAX_WIDTH ? thumb.resize({ width: CONTEXT_MAX_WIDTH }) : thumb
  const window = await deps.activeWindow().catch(() => null)
  return {
    png: cropped.toPNG(),
    contextPng: context.toPNG(),
    width: pixelCrop.width,
    height: pixelCrop.height,
    scale,
    display: display.id,
    context: { crop, screen: display.bounds },
    window
  }
}

export function createScreenCapture(deps: ScreenCaptureDeps): ScreenCapture {
  const capability = (): CaptureCapability => {
    const posture = staticCapabilities(deps.basics).capture
    if (deps.basics.platform === 'darwin' && deps.getMediaAccessStatus?.('screen') === 'granted') {
      return { mode: 'available', message: '' }
    }
    const mode = posture.status === 'needs-permission' ? 'needs-permission' : 'unavailable'
    return posture.status === 'available'
      ? { mode: 'available', message: '' }
      : {
          mode,
          message: posture.message,
          ...(posture.settingsUrl ? { settingsUrl: posture.settingsUrl } : {})
        }
  }

  /** Why a capture may not happen right now: the setting, then the platform. */
  const refuse = (): CaptureUnavailable | null => {
    if (deps.isEnabled?.() === false) {
      return { reason: 'disabled', message: 'SOL sees your screen is off.' }
    }
    const cap = capability()
    if (cap.mode === 'available') return null
    return {
      reason: cap.mode,
      message: cap.message,
      ...(cap.settingsUrl ? { settingsUrl: cap.settingsUrl } : {})
    }
  }

  const captureRegion = async (region: Rect): Promise<CaptureResult | CaptureUnavailable> => {
    const refused = refuse()
    if (refused) return refused
    try {
      const display = deps.getDisplayNearestPoint({
        x: region.x + region.width / 2,
        y: region.y + region.height / 2
      })
      const crop = intersect(region, display.bounds)
      if (crop.width <= 0 || crop.height <= 0) {
        return { reason: 'empty-region', message: 'The circled area is off-screen.' }
      }
      return await grab(deps, display, crop)
    } catch (error) {
      // No pixels, no titles in the log — only the failure class.
      deps.warn(
        `[capture] region capture failed: ${error instanceof Error ? error.message : 'unknown'}`
      )
      return { reason: 'error', message: 'Screen capture failed on this machine.' }
    }
  }

  return { capability, captureRegion }
}

/** Production deps over the real Electron modules. */
export function realScreenCaptureDeps(basics: PlatformBasics): ScreenCaptureDeps {
  return {
    basics,
    getSources: (options) => desktopCapturer.getSources(options),
    getDisplayNearestPoint: (point) => screen.getDisplayNearestPoint(point),
    ...(basics.platform === 'darwin'
      ? { getMediaAccessStatus: (t: 'screen') => systemPreferences.getMediaAccessStatus(t) }
      : {}),
    activeWindow: () => activeWindow(basics, realActiveWindowDeps),
    warn: (message) => console.warn(message)
  }
}
