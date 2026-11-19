// SOLUSDEV-327 — the SOL sidebar's one open state (it follows the person across screens) and its
// remembered width (sol-sidebar.md §2–3).
import { beforeEach, describe, expect, it } from 'vitest'
import {
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  clampSidebarWidth,
  scaledSidebarWidth,
  selectSidebarOpen,
  useSolSidebarStore
} from './solSidebarStore'

beforeEach(() => {
  useSolSidebarStore.getState().reset()
})

describe('solSidebarStore', () => {
  it('starts closed at the default width', () => {
    const state = useSolSidebarStore.getState()
    expect(selectSidebarOpen(state, 'workspace')).toBe(false)
    expect(state.width).toBe(SIDEBAR_DEFAULT_WIDTH)
  })

  it('follows the person across screens', () => {
    useSolSidebarStore.getState().toggle()
    const state = useSolSidebarStore.getState()
    expect(selectSidebarOpen(state, 'workspace')).toBe(true)
    expect(selectSidebarOpen(state, 'bench')).toBe(true)
    expect(selectSidebarOpen(state, 'alert')).toBe(true)
    useSolSidebarStore.getState().setOpen(false)
    expect(selectSidebarOpen(useSolSidebarStore.getState(), 'home')).toBe(false)
  })

  it('is never shown on the SOL page, and stays open for the next screen', () => {
    useSolSidebarStore.getState().setOpen(true)
    const state = useSolSidebarStore.getState()
    expect(selectSidebarOpen(state, 'sol')).toBe(false)
    expect(selectSidebarOpen(state, 'home')).toBe(true)
  })

  it('clamps the width between 320 and 480', () => {
    expect(clampSidebarWidth(100)).toBe(SIDEBAR_MIN_WIDTH)
    expect(clampSidebarWidth(9000)).toBe(SIDEBAR_MAX_WIDTH)
    expect(clampSidebarWidth(400.6)).toBe(401)
    expect(clampSidebarWidth(Number.NaN)).toBe(SIDEBAR_DEFAULT_WIDTH)
    useSolSidebarStore.getState().setWidth(700)
    expect(useSolSidebarStore.getState().width).toBe(SIDEBAR_MAX_WIDTH)
  })
})

describe('solSidebarStore — window share and storage (SOLUSDEV-328)', () => {
  it('scales its starting width with the window, 22% held to 360–480', () => {
    expect(scaledSidebarWidth(1024)).toBe(SIDEBAR_DEFAULT_WIDTH)
    expect(scaledSidebarWidth(1920)).toBe(422)
    expect(scaledSidebarWidth(2560)).toBe(SIDEBAR_MAX_WIDTH)
    expect(scaledSidebarWidth(Number.NaN)).toBe(SIDEBAR_DEFAULT_WIDTH)
  })

  it('is not user-sized until the person resizes it, and reset forgets it', () => {
    expect(useSolSidebarStore.getState().userSized).toBe(false)
    useSolSidebarStore.getState().setWidth(400)
    expect(useSolSidebarStore.getState().userSized).toBe(true)
    useSolSidebarStore.getState().reset()
    expect(useSolSidebarStore.getState().userSized).toBe(false)
  })

  it('treats a stored pre-328 width as user-sized only when it was dragged off the default', async () => {
    localStorage.setItem(
      'solus.sol-sidebar',
      JSON.stringify({ state: { open: true, width: SIDEBAR_DEFAULT_WIDTH }, version: 1 })
    )
    await useSolSidebarStore.persist.rehydrate()
    expect(useSolSidebarStore.getState().userSized).toBe(false)
    localStorage.setItem(
      'solus.sol-sidebar',
      JSON.stringify({ state: { open: true, width: 420 }, version: 1 })
    )
    await useSolSidebarStore.persist.rehydrate()
    expect(useSolSidebarStore.getState().userSized).toBe(true)
    localStorage.setItem(
      'solus.sol-sidebar',
      JSON.stringify({ state: { open: true, width: 420, userSized: 'yes' }, version: 1 })
    )
    await useSolSidebarStore.persist.rehydrate()
    expect(useSolSidebarStore.getState().userSized).toBe(false)
    for (const malformed of ['true', 1, {}]) {
      localStorage.setItem(
        'solus.sol-sidebar',
        JSON.stringify({ state: { open: true, width: 420, userSized: malformed }, version: 1 })
      )
      await useSolSidebarStore.persist.rehydrate()
      expect(useSolSidebarStore.getState().userSized).toBe(false)
    }
    localStorage.clear()
  })

  it('restores only a boolean open flag from storage', async () => {
    localStorage.setItem(
      'solus.sol-sidebar',
      JSON.stringify({ state: { open: 'yes', width: '9000' }, version: 1 })
    )
    await useSolSidebarStore.persist.rehydrate()
    const state = useSolSidebarStore.getState()
    expect(state.open).toBe(false)
    expect(state.width).toBe(SIDEBAR_DEFAULT_WIDTH)
    localStorage.setItem(
      'solus.sol-sidebar',
      JSON.stringify({ state: { open: true, width: 400 }, version: 1 })
    )
    await useSolSidebarStore.persist.rehydrate()
    expect(useSolSidebarStore.getState().open).toBe(true)
    expect(useSolSidebarStore.getState().width).toBe(400)
    localStorage.clear()
  })
})
