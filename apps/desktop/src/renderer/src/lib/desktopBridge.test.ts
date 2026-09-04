import { describe, it, expect, afterEach } from 'vitest'
import {
  getDesktopOAuthBridge,
  getDesktopCompanionBridge,
  getDesktopExtensionsBridge,
  getDesktopPlatform
} from './desktopBridge'

interface SolusWindow {
  solus?: unknown
}

afterEach(() => {
  delete (window as unknown as SolusWindow).solus
})

describe('getDesktopOAuthBridge', () => {
  it('returns null when not running under Electron', () => {
    expect(getDesktopOAuthBridge()).toBeNull()
  })

  it('returns the oauth bridge when present', () => {
    const oauth = { getRedirectUrl: async () => 'x', awaitGithub: async () => ({}) }
    ;(window as unknown as SolusWindow).solus = { oauth }
    expect(getDesktopOAuthBridge()).toBe(oauth)
  })
})

describe('getDesktopCompanionBridge', () => {
  it('returns null when not running under Electron', () => {
    expect(getDesktopCompanionBridge()).toBeNull()
  })

  it('returns the companion bridge when present', () => {
    const bridge = { setToken: async () => undefined }
    ;(window as unknown as SolusWindow).solus = { bridge }
    expect(getDesktopCompanionBridge()).toBe(bridge)
  })
})

describe('getDesktopPlatform', () => {
  it('returns null outside Electron and the platform string under it', () => {
    const w = window as unknown as { solus?: { platform?: string } }
    delete w.solus
    expect(getDesktopPlatform()).toBeNull()
    w.solus = { platform: 'darwin' }
    expect(getDesktopPlatform()).toBe('darwin')
    delete w.solus
  })
})

describe('getDesktopExtensionsBridge', () => {
  it('returns null when not running under Electron', () => {
    expect(getDesktopExtensionsBridge()).toBeNull()
  })

  it('returns the extensions bridge when present', () => {
    const extensions = { index: async () => ({ schema_version: 1, installed: {} }) }
    ;(window as unknown as SolusWindow).solus = { extensions }
    expect(getDesktopExtensionsBridge()).toBe(extensions)
  })
})
