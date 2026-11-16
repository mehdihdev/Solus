// SOLUSDEV-327 — sidebar open/close keeps the store and the event in step.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { closeSidebar, toggleSidebar } from './sidebarActions'
import { selectSidebarOpen, useSolSidebarStore } from './solSidebarStore'
import * as events from './sidebarEvents'

vi.mock('./sidebarEvents', () => ({ reportSidebarToggled: vi.fn() }))
const report = vi.mocked(events.reportSidebarToggled)
const isOpen = (key: string): boolean => selectSidebarOpen(useSolSidebarStore.getState(), key)

beforeEach(() => {
  vi.clearAllMocks()
  useSolSidebarStore.getState().reset()
})

describe('sidebarActions', () => {
  it('toggles open then closed, reporting each', () => {
    expect(toggleSidebar('home', 'button')).toBe(true)
    expect(isOpen('home')).toBe(true)
    expect(report).toHaveBeenLastCalledWith('open', 'home', 'button')
    expect(toggleSidebar('home', 'shortcut')).toBe(false)
    expect(report).toHaveBeenLastCalledWith('close', 'home', 'shortcut')
  })

  it('never toggles on the SOL page and reports nothing', () => {
    expect(toggleSidebar('sol', 'shortcut')).toBe(false)
    expect(report).not.toHaveBeenCalled()
  })

  it('closes with the action that closed it', () => {
    toggleSidebar('bench', 'button')
    closeSidebar('bench', 'header', 'expand')
    expect(isOpen('bench')).toBe(false)
    expect(report).toHaveBeenLastCalledWith('expand', 'bench', 'header')
    closeSidebar('bench', 'escape')
    expect(report).toHaveBeenLastCalledWith('close', 'bench', 'escape')
  })
})
