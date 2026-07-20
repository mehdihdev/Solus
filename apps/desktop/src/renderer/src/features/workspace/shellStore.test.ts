// Shell interaction state: toast + last-main-screen navigation memory.
// SOLUSDEV-152 removed the prototype alert/chat/anomaly state with the demo.
import { describe, it, expect, beforeEach } from 'vitest'
import { useShellStore } from './shellStore'

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
