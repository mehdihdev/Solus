// SOLUSDEV-327 — the SOL sidebar's per-screen open state and remembered width (sol-sidebar.md §2–3).
import { beforeEach, describe, expect, it } from 'vitest'
import {
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  clampSidebarWidth,
  selectSidebarOpen,
  sidebarKey,
  useSolSidebarStore
} from './solSidebarStore'

beforeEach(() => {
  useSolSidebarStore.getState().reset()
})

describe('solSidebarStore', () => {
  it('starts closed everywhere at the default width', () => {
    const state = useSolSidebarStore.getState()
    expect(selectSidebarOpen(state, 'workspace')).toBe(false)
    expect(selectSidebarOpen(state, 'home')).toBe(false)
    expect(state.width).toBe(SIDEBAR_DEFAULT_WIDTH)
  })

  it('remembers open or closed per screen', () => {
    useSolSidebarStore.getState().toggle('workspace')
    const state = useSolSidebarStore.getState()
    expect(selectSidebarOpen(state, 'workspace')).toBe(true)
    expect(selectSidebarOpen(state, 'bench')).toBe(false)
    useSolSidebarStore.getState().setOpen('workspace', false)
    expect(selectSidebarOpen(useSolSidebarStore.getState(), 'workspace')).toBe(false)
  })

  it('never opens on the SOL page', () => {
    useSolSidebarStore.getState().toggle('sol')
    expect(selectSidebarOpen(useSolSidebarStore.getState(), 'sol')).toBe(false)
  })

  it('does not mutate the previous open map', () => {
    const before = useSolSidebarStore.getState().openByScreen
    useSolSidebarStore.getState().toggle('home')
    expect(before).toEqual({})
  })

  it('clamps the width between 320 and 480', () => {
    expect(clampSidebarWidth(100)).toBe(SIDEBAR_MIN_WIDTH)
    expect(clampSidebarWidth(9000)).toBe(SIDEBAR_MAX_WIDTH)
    expect(clampSidebarWidth(400.6)).toBe(401)
    expect(clampSidebarWidth(Number.NaN)).toBe(SIDEBAR_DEFAULT_WIDTH)
    useSolSidebarStore.getState().setWidth(700)
    expect(useSolSidebarStore.getState().width).toBe(SIDEBAR_MAX_WIDTH)
  })

  it('keys detail routes by their kind', () => {
    expect(sidebarKey({ name: 'workspace' })).toBe('workspace')
    expect(sidebarKey({ name: 'alert', alertId: 'a1' })).toBe('alert')
    expect(sidebarKey({ name: 'ext-page', slug: 'x' })).toBe('ext-page')
  })
})
