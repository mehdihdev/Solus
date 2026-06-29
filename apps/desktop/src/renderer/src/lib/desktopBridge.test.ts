import { describe, it, expect, afterEach } from 'vitest'
import { getDesktopOAuthBridge } from './desktopBridge'

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
