import { describe, it, expect, afterEach } from 'vitest'
import { getDesktopOAuthBridge, getDesktopCompanionBridge } from './desktopBridge'

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
