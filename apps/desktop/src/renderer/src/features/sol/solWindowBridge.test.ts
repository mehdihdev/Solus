// SOLX-02: typed access to the sol-window detach/attach invokes (desktopBridge
// idiom, scoped to this feature). Null outside Electron so the orb degrades.
import { describe, it, expect, afterEach, vi } from 'vitest'
import { getSolWindowBridge } from './solWindowBridge'

const w = window as unknown as { solus?: unknown }

afterEach(() => {
  delete w.solus
})

describe('getSolWindowBridge', () => {
  it('returns null outside the Electron shell', () => {
    expect(getSolWindowBridge()).toBeNull()
  })

  it('returns null when the preload predates the sol-window surface', () => {
    w.solus = { oauth: {} }
    expect(getSolWindowBridge()).toBeNull()
  })

  it('returns the preload surface when present', () => {
    const solWindow = { detach: vi.fn(), attach: vi.fn() }
    w.solus = { solWindow }
    expect(getSolWindowBridge()).toBe(solWindow)
  })
})
