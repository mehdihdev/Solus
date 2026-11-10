// SOLUSDEV-324: the summon picture holder. Wireflow sol-window §D: "SOL can take
// a picture of your screen when you summon it … uses it for that one question,
// and then discards it." refresh() runs at summon (before the pill shows);
// take() hands it to exactly one turn; nothing outlives that or the setting.
import { describe, expect, it, vi } from 'vitest'
import { createSummonShot, SUMMON_SHOT_MAX_LATENCY_MS } from './summonShot'
import type { CaptureUnavailable, ScreenShot } from './screenCapture'

vi.mock('electron', () => ({}))

const SHOT: ScreenShot = {
  jpeg: Buffer.from('jpeg-bytes'),
  width: 1920,
  height: 1080,
  display: 1,
  window: { app: 'Firefox', title: 'Gradescope' }
}

function harness(result: ScreenShot | CaptureUnavailable = SHOT): {
  shot: ReturnType<typeof createSummonShot>
  captureScreen: ReturnType<typeof vi.fn>
} {
  const captureScreen = vi.fn(async () => result)
  const shot = createSummonShot({
    capture: { captureScreen },
    cursor: () => ({ x: 5, y: 6 }),
    now: () => 42
  })
  return { shot, captureScreen }
}

describe('createSummonShot', () => {
  it('refresh captures the display under the cursor; take hands it over exactly once', async () => {
    const { shot, captureScreen } = harness()
    await shot.refresh()
    expect(captureScreen).toHaveBeenCalledWith({ x: 5, y: 6 })
    expect(shot.take()).toEqual({
      jpegBase64: SHOT.jpeg.toString('base64'),
      width: 1920,
      height: 1080,
      source: { app: 'Firefox', title: 'Gradescope' },
      capturedAt: 42
    })
    expect(shot.take()).toBeNull()
  })

  it('nothing to take before any summon', () => {
    expect(harness().shot.take()).toBeNull()
  })

  it('a refused capture (setting off, no permission) leaves nothing — and drops the old one', async () => {
    const captureScreen = vi
      .fn<() => Promise<ScreenShot | CaptureUnavailable>>()
      .mockResolvedValueOnce(SHOT)
      .mockResolvedValueOnce({ reason: 'disabled', message: 'off' })
    const shot = createSummonShot({ capture: { captureScreen }, cursor: () => ({ x: 0, y: 0 }) })
    await shot.refresh()
    await shot.refresh()
    expect(shot.take()).toBeNull()
  })

  it('clear() forgets it, and a capture still in flight when cleared never lands', async () => {
    let resolve: (r: ScreenShot) => void = () => undefined
    const captureScreen = vi.fn(
      () =>
        new Promise<ScreenShot | CaptureUnavailable>((r) => {
          resolve = r
        })
    )
    const shot = createSummonShot({ capture: { captureScreen }, cursor: () => ({ x: 0, y: 0 }) })
    const pending = shot.refresh()
    shot.clear()
    resolve(SHOT)
    await pending
    expect(shot.take()).toBeNull()
  })

  it('a newer summon wins over an older capture that finishes late', async () => {
    const resolvers: Array<(r: ScreenShot) => void> = []
    const captureScreen = vi.fn(
      () =>
        new Promise<ScreenShot | CaptureUnavailable>((r) => {
          resolvers.push(r)
        })
    )
    const shot = createSummonShot({ capture: { captureScreen }, cursor: () => ({ x: 0, y: 0 }) })
    const first = shot.refresh()
    const second = shot.refresh()
    resolvers[1]({ ...SHOT, width: 2 })
    resolvers[0]({ ...SHOT, width: 1 })
    await Promise.all([first, second])
    expect(shot.take()?.width).toBe(2)
  })

  it('captures the display nearest the summon point when one is given', async () => {
    const { shot, captureScreen } = harness()
    await shot.refresh({ x: 3000, y: 9 })
    expect(captureScreen).toHaveBeenCalledWith({ x: 3000, y: 9 })
  })

  it('a capture landing past SUMMON_SHOT_MAX_LATENCY_MS is dropped (the pill may be in it)', async () => {
    let t = 0
    const captureScreen = vi.fn(async () => {
      t += SUMMON_SHOT_MAX_LATENCY_MS + 1
      return SHOT
    })
    const shot = createSummonShot({
      capture: { captureScreen },
      cursor: () => ({ x: 0, y: 0 }),
      now: () => t
    })
    await shot.refresh()
    expect(shot.take()).toBeNull()
  })

  it('a capture landing after a take() never rides a later question', async () => {
    let resolve: (r: ScreenShot) => void = () => undefined
    const captureScreen = vi.fn(
      () =>
        new Promise<ScreenShot | CaptureUnavailable>((r) => {
          resolve = r
        })
    )
    const shot = createSummonShot({ capture: { captureScreen }, cursor: () => ({ x: 0, y: 0 }) })
    const pending = shot.refresh()
    expect(shot.take()).toBeNull() // the quick first question went without
    resolve(SHOT)
    await pending
    expect(shot.take()).toBeNull()
  })

  it('a throwing capturer never rejects refresh', async () => {
    const captureScreen = vi.fn(async () => {
      throw new Error('boom')
    })
    const shot = createSummonShot({ capture: { captureScreen }, cursor: () => ({ x: 0, y: 0 }) })
    await expect(shot.refresh()).resolves.toBeUndefined()
    expect(shot.take()).toBeNull()
  })
})
