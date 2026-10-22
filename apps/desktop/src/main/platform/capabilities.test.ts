import { describe, expect, it } from 'vitest'
import {
  MAC_ACCESSIBILITY_URL,
  MAC_SCREEN_RECORDING_URL,
  detectPlatformBasics,
  isSystemSettingsUrl,
  staticCapabilities
} from './capabilities'

describe('isSystemSettingsUrl (SOLUSDEV-318)', () => {
  it('accepts exactly the two macOS privacy panes Solus links to', () => {
    expect(isSystemSettingsUrl(MAC_SCREEN_RECORDING_URL)).toBe(true)
    expect(isSystemSettingsUrl(MAC_ACCESSIBILITY_URL)).toBe(true)
  })

  it('refuses anything else, including look-alike settings URLs', () => {
    for (const url of [
      undefined,
      '',
      'https://solusforge.com',
      'x-apple.systempreferences:com.apple.preference.security',
      `${MAC_SCREEN_RECORDING_URL}&x=1`,
      'file:///Applications/Calculator.app'
    ]) {
      expect(isSystemSettingsUrl(url)).toBe(false)
    }
  })
})

describe('detectPlatformBasics', () => {
  it('reads the Linux session type from XDG_SESSION_TYPE or WAYLAND_DISPLAY', () => {
    expect(detectPlatformBasics({ XDG_SESSION_TYPE: 'x11' }, 'linux', 'arm64').session).toBe('x11')
    expect(detectPlatformBasics({ XDG_SESSION_TYPE: 'wayland' }, 'linux', 'x64').session).toBe(
      'wayland'
    )
    expect(detectPlatformBasics({ WAYLAND_DISPLAY: 'wayland-0' }, 'linux', 'x64').session).toBe(
      'wayland'
    )
    expect(detectPlatformBasics({}, 'linux', 'x64').session).toBe('x11')
  })
  it('maps the other OSes without looking at the environment', () => {
    expect(detectPlatformBasics({ WAYLAND_DISPLAY: 'x' }, 'win32', 'arm64').session).toBe('windows')
    expect(detectPlatformBasics({}, 'darwin', 'arm64').session).toBe('macos')
    expect(detectPlatformBasics({}, 'freebsd', 'x64').session).toBe('unknown')
  })
})

describe('staticCapabilities', () => {
  it('tries portal shortcuts while retaining Wayland hook/capture restrictions', () => {
    const caps = staticCapabilities({ platform: 'linux', arch: 'x64', session: 'wayland' })
    expect(caps.hook.status).toBe('unavailable')
    expect(caps.globalShortcuts.status).toBe('unknown')
    expect(caps.capture.status).toBe('unavailable')
    expect(caps.capture.message).toMatch(/Wayland/)
  })
  it('marks the hook unavailable on Linux arm64 (the published prebuild is x86-64)', () => {
    const caps = staticCapabilities({ platform: 'linux', arch: 'arm64', session: 'x11' })
    expect(caps.hook.status).toBe('unavailable')
    expect(caps.hook.message).toMatch(/Ctrl\+Shift\+C/)
    expect(caps.capture.status).toBe('available')
    expect(caps.globalShortcuts.status).toBe('available')
  })
  it('needs permissions on macOS and links to the panes', () => {
    const caps = staticCapabilities({ platform: 'darwin', arch: 'arm64', session: 'macos' })
    expect(caps.hook).toMatchObject({
      status: 'needs-permission',
      settingsUrl: MAC_ACCESSIBILITY_URL
    })
    expect(caps.capture).toMatchObject({
      status: 'needs-permission',
      settingsUrl: MAC_SCREEN_RECORDING_URL
    })
  })
  it('leaves the hook to the self-test on Windows and Linux x64', () => {
    for (const basics of [
      { platform: 'win32' as const, arch: 'x64', session: 'windows' as const },
      { platform: 'linux' as const, arch: 'x64', session: 'x11' as const }
    ]) {
      const caps = staticCapabilities(basics)
      expect(caps.hook.status).toBe('unknown')
      expect(caps.capture.status).toBe('available')
    }
  })
})
