// SOLUSDEV-252 S3: the §6 ScreenCapture interface over injected desktopCapturer /
// screen / nativeImage slices. Every failure is a CaptureUnavailable value.
import { describe, it, expect, vi } from 'vitest'
import { MAC_SCREEN_RECORDING_URL, type PlatformBasics } from '../platform/capabilities'
import {
  createScreenCapture,
  CONTEXT_MAX_WIDTH,
  type CaptureImage,
  type ScreenCaptureDeps
} from './screenCapture'

vi.mock('electron', () => ({}))

const X11: PlatformBasics = { platform: 'linux', arch: 'x64', session: 'x11' }
const MAC: PlatformBasics = { platform: 'darwin', arch: 'arm64', session: 'macos' }
const WAYLAND: PlatformBasics = { platform: 'linux', arch: 'x64', session: 'wayland' }

interface FakeImage extends CaptureImage {
  ops: string[]
}

function fakeImage(width: number, height: number, ops: string[] = []): FakeImage {
  return {
    ops,
    getSize: () => ({ width, height }),
    crop: (r) =>
      fakeImage(r.width, r.height, [...ops, `crop:${r.x},${r.y},${r.width},${r.height}`]),
    resize: (o) =>
      fakeImage(o.width, Math.round((height * o.width) / width), [...ops, `resize:${o.width}`]),
    toPNG: () => Buffer.from(ops.join('|'))
  }
}

const DISPLAY_A = { id: 11, bounds: { x: 0, y: 0, width: 1920, height: 1080 }, scaleFactor: 1 }
const DISPLAY_B = { id: 22, bounds: { x: 1920, y: 0, width: 1440, height: 900 }, scaleFactor: 2 }

function deps(over: Partial<ScreenCaptureDeps> = {}, basics = X11): ScreenCaptureDeps {
  return {
    basics,
    getSources: async ({ thumbnailSize }) => [
      {
        id: 'screen:11:0',
        display_id: '11',
        thumbnail: fakeImage(thumbnailSize.width, thumbnailSize.height)
      },
      {
        id: 'screen:22:0',
        display_id: '22',
        thumbnail: fakeImage(thumbnailSize.width, thumbnailSize.height)
      }
    ],
    getDisplayNearestPoint: (p) => (p.x >= 1920 ? DISPLAY_B : DISPLAY_A),
    activeWindow: async () => ({ app: 'kicad', title: 'main.kicad_sch' }),
    warn: vi.fn(),
    ...over
  }
}

describe('capability', () => {
  it('X11 → available', () => {
    expect(createScreenCapture(deps()).capability()).toEqual({ mode: 'available', message: '' })
  })
  it('Wayland → unavailable with the plain-language message', () => {
    const c = createScreenCapture(deps({}, WAYLAND)).capability()
    expect(c.mode).toBe('unavailable')
    expect(c.message).toMatch(/Wayland/)
  })
  it('darwin without Screen Recording → needs-permission + deep link; granted → available', () => {
    const denied = createScreenCapture(deps({ getMediaAccessStatus: () => 'denied' }, MAC))
    expect(denied.capability()).toMatchObject({
      mode: 'needs-permission',
      settingsUrl: MAC_SCREEN_RECORDING_URL
    })
    const granted = createScreenCapture(deps({ getMediaAccessStatus: () => 'granted' }, MAC))
    expect(granted.capability().mode).toBe('available')
  })
})

describe('captureRegion', () => {
  registerCaptureGeometryTests()
  registerCaptureAvailabilityTests()
  registerCaptureFailuresTests()
})

function registerCaptureGeometryTests(): void {
  it('crops the matching display source at scaleFactor 2 and downscales the context', async () => {
    const result = await createScreenCapture(deps()).captureRegion({
      x: 2020,
      y: 100,
      width: 300,
      height: 200
    })
    expect('reason' in result).toBe(false)
    if ('reason' in result) return
    expect(result.png.toString()).toBe('crop:200,200,600,400')
    expect(result).toMatchObject({ width: 600, height: 400, scale: 2, display: 22 })
    expect(result.context).toEqual({
      crop: { x: 2020, y: 100, width: 300, height: 200 },
      screen: DISPLAY_B.bounds
    })
    expect(result.contextPng.toString()).toBe(`resize:${CONTEXT_MAX_WIDTH}`)
    expect(result.window).toEqual({ app: 'kicad', title: 'main.kicad_sch' })
  })

  it('clamps a region hanging off the display edge; no source match → first source', async () => {
    const d = deps({
      getSources: async ({ thumbnailSize }) => [
        {
          id: 'screen:0:0',
          display_id: '',
          thumbnail: fakeImage(thumbnailSize.width, thumbnailSize.height)
        }
      ]
    })
    const result = await createScreenCapture(d).captureRegion({
      x: -50,
      y: 1000,
      width: 200,
      height: 200
    })
    if ('reason' in result) throw new Error(result.message)
    expect(result.png.toString()).toBe('crop:0,1000,150,80')
    expect(result.contextPng.toString()).toBe(`resize:${CONTEXT_MAX_WIDTH}`)
  })

  it('a small screen is not upscaled for context', async () => {
    const small = { id: 1, bounds: { x: 0, y: 0, width: 1024, height: 768 }, scaleFactor: 1 }
    const result = await createScreenCapture(
      deps({ getDisplayNearestPoint: () => small })
    ).captureRegion({ x: 0, y: 0, width: 10, height: 10 })
    if ('reason' in result) throw new Error(result.message)
    expect(result.contextPng.toString()).toBe('')
  })

  it('region entirely off-screen → CaptureUnavailable(empty-region)', async () => {
    const result = await createScreenCapture(deps()).captureRegion({
      x: 5000,
      y: 5000,
      width: 10,
      height: 10
    })
    expect(result).toMatchObject({ reason: 'empty-region' })
  })
}

function registerCaptureAvailabilityTests(): void {
  it('setting off → CaptureUnavailable(disabled) before any source or permission work (§7)', async () => {
    const getSources = vi.fn()
    const getMediaAccessStatus = vi.fn(() => 'granted')
    const result = await createScreenCapture(
      deps({ getSources, getMediaAccessStatus, isEnabled: () => false }, MAC)
    ).captureRegion({ x: 0, y: 0, width: 10, height: 10 })
    expect(result).toEqual({ reason: 'disabled', message: 'SOL sees your screen is off.' })
    expect(getSources).not.toHaveBeenCalled()
    expect(getMediaAccessStatus).not.toHaveBeenCalled()
    const on = await createScreenCapture(deps({ isEnabled: () => true })).captureRegion({
      x: 0,
      y: 0,
      width: 10,
      height: 10
    })
    expect('reason' in on).toBe(false)
  })

  it('permission missing → CaptureUnavailable(needs-permission) without touching getSources', async () => {
    const getSources = vi.fn()
    const result = await createScreenCapture(
      deps({ getSources, getMediaAccessStatus: () => 'not-determined' }, MAC)
    ).captureRegion({ x: 0, y: 0, width: 10, height: 10 })
    expect(result).toMatchObject({
      reason: 'needs-permission',
      settingsUrl: MAC_SCREEN_RECORDING_URL
    })
    expect(getSources).not.toHaveBeenCalled()
  })

  it('Wayland → CaptureUnavailable(unavailable)', async () => {
    const result = await createScreenCapture(deps({}, WAYLAND)).captureRegion({
      x: 0,
      y: 0,
      width: 10,
      height: 10
    })
    expect(result).toMatchObject({ reason: 'unavailable' })
  })
}

function registerCaptureFailuresTests(): void {
  it('getSources throwing or returning nothing → CaptureUnavailable(error), warned, never thrown', async () => {
    const warn = vi.fn()
    const boom = createScreenCapture(
      deps({
        warn,
        getSources: async () => {
          throw new Error('capturer exploded')
        }
      })
    )
    await expect(boom.captureRegion({ x: 0, y: 0, width: 10, height: 10 })).resolves.toMatchObject({
      reason: 'error'
    })
    expect(warn).toHaveBeenCalledTimes(1)
    const empty = createScreenCapture(deps({ getSources: async () => [] }))
    await expect(empty.captureRegion({ x: 0, y: 0, width: 10, height: 10 })).resolves.toMatchObject(
      {
        reason: 'error'
      }
    )
  })

  it('an activeWindow failure degrades to window: null, not a failed capture', async () => {
    const result = await createScreenCapture(
      deps({
        activeWindow: async () => {
          throw new Error('xprop')
        }
      })
    ).captureRegion({ x: 0, y: 0, width: 10, height: 10 })
    if ('reason' in result) throw new Error(result.message)
    expect(result.window).toBeNull()
  })
}
