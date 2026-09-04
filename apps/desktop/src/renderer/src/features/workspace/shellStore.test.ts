// Shell interaction state: toast + last-main-screen navigation memory.
// SOLUSDEV-152 removed the prototype alert/chat/anomaly state with the demo.
import { describe, it, expect, beforeEach } from 'vitest'
import { useShellStore, routeKey } from './shellStore'

beforeEach(() => useShellStore.getState().reset())

describe('toast', () => {
  it('stores and clears the toast', () => {
    useShellStore.getState().setToast({ title: 'T', body: 'B', action: 'View' })
    expect(useShellStore.getState().toast?.title).toBe('T')
    useShellStore.getState().clearToast()
    expect(useShellStore.getState().toast).toBeNull()
  })
})

describe('lastMain', () => {
  it('tracks the last main screen for back navigation', () => {
    useShellStore.getState().setLastMain('team')
    expect(useShellStore.getState().lastMain).toBe('team')
  })

  it('resets to home', () => {
    useShellStore.getState().setLastMain('bench')
    useShellStore.getState().reset()
    expect(useShellStore.getState().lastMain).toBe('home')
    expect(useShellStore.getState().toast).toBeNull()
  })
})

describe('routeKey', () => {
  it('keys main screens by name, alerts by id and extension pages by slug', () => {
    expect(routeKey({ name: 'bench' })).toBe('bench')
    expect(routeKey({ name: 'alert', alertId: 'a1' })).toBe('alert-a1')
    expect(routeKey({ name: 'ext-page', slug: 'bom' })).toBe('ext-page-bom')
  })

  it('gives two extension pages distinct keys so the screen transition replays', () => {
    expect(routeKey({ name: 'ext-page', slug: 'bom' })).not.toBe(
      routeKey({ name: 'ext-page', slug: 'cam' })
    )
  })
})
