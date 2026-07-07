// Shell interaction state: alert resolution, bench anomaly, toast, SOL chat.
import { describe, it, expect, beforeEach } from 'vitest'
import { useShellStore, alertsWithState, openAlertCount } from './shellStore'
import { ALERTS } from './workspaceData.constants'

beforeEach(() => useShellStore.getState().reset())

describe('alert resolution', () => {
  it('marks an alert resolved and derives state', () => {
    useShellStore.getState().resolveAlert('a1')
    const alerts = alertsWithState(ALERTS, useShellStore.getState().resolved)
    expect(alerts.find((a) => a.id === 'a1')?.state).toBe('resolved')
    // a3 ships resolved in the data; a2 stays open.
    expect(openAlertCount(alerts)).toBe(1)
  })

  it('counts two open alerts initially', () => {
    const alerts = alertsWithState(ALERTS, useShellStore.getState().resolved)
    expect(openAlertCount(alerts)).toBe(2)
  })
})

describe('toast + anomaly + chat', () => {
  it('stores and clears the toast', () => {
    useShellStore.getState().setToast({ title: 'T', body: 'B', action: 'View', alertId: 'a1' })
    expect(useShellStore.getState().toast?.title).toBe('T')
    useShellStore.getState().clearToast()
    expect(useShellStore.getState().toast).toBeNull()
  })

  it('tracks the magic-moment toast having fired', () => {
    expect(useShellStore.getState().toastShown).toBe(false)
    useShellStore.getState().markToastShown()
    expect(useShellStore.getState().toastShown).toBe(true)
  })

  it('appends chat messages immutably', () => {
    useShellStore.getState().appendChat({ role: 'user', text: 'hi' })
    useShellStore.getState().appendChat({ role: 'sol', scriptKey: 'hello' })
    expect(useShellStore.getState().chat).toHaveLength(2)
  })

  it('sets anomaly state', () => {
    useShellStore.getState().setAnomaly('active')
    expect(useShellStore.getState().anomaly).toBe('active')
  })
})
