// SOLUSDEV-323: the main window's macOS traffic lights move per screen — the
// workspace's 44 px title row, onboarding's 64 px header.
import { describe, expect, it, vi } from 'vitest'
import { TRAFFIC_LIGHTS, applyWindowChrome, isWindowChrome } from './windowChrome'

const fakeWindow = () => ({ setWindowButtonPosition: vi.fn() })

describe('isWindowChrome', () => {
  it('accepts exactly the two chrome kinds', () => {
    expect(isWindowChrome('title')).toBe(true)
    expect(isWindowChrome('onboarding')).toBe(true)
    expect(isWindowChrome('kiosk')).toBe(false)
    expect(isWindowChrome({ x: 0, y: 0 })).toBe(false)
    expect(isWindowChrome(undefined)).toBe(false)
  })
})

describe('TRAFFIC_LIGHTS', () => {
  it('centres the 12 px lights in each header (44 px title row, 64 px onboarding header)', () => {
    expect(TRAFFIC_LIGHTS.title.y + 6).toBe(22)
    expect(TRAFFIC_LIGHTS.onboarding.y + 6).toBe(32)
  })
})

describe('applyWindowChrome', () => {
  it('moves the lights on macOS', () => {
    const win = fakeWindow()
    expect(applyWindowChrome(win, 'onboarding', 'darwin')).toBe(true)
    expect(win.setWindowButtonPosition).toHaveBeenCalledWith(TRAFFIC_LIGHTS.onboarding)
  })

  it('does nothing off macOS, for an unknown kind, or with no window', () => {
    const win = fakeWindow()
    expect(applyWindowChrome(win, 'onboarding', 'win32')).toBe(false)
    expect(applyWindowChrome(win, 'kiosk', 'darwin')).toBe(false)
    expect(applyWindowChrome(null, 'title', 'darwin')).toBe(false)
    expect(win.setWindowButtonPosition).not.toHaveBeenCalled()
  })
})
