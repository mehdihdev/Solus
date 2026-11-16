// SOLUSDEV-327 — ⌘J / Ctrl J toggles the sidebar (sol-sidebar.md §2).
import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { isSidebarShortcut, sidebarShortcutHint, useSidebarHotkey } from './sidebarHotkey'

const key = (over: Partial<KeyboardEventInit> = {}): KeyboardEventInit => ({
  key: 'j',
  metaKey: false,
  ctrlKey: false,
  altKey: false,
  shiftKey: false,
  ...over
})

describe('isSidebarShortcut', () => {
  it('is ⌘J on macOS and Ctrl J elsewhere', () => {
    expect(isSidebarShortcut(new KeyboardEvent('keydown', key({ metaKey: true })), true)).toBe(true)
    expect(isSidebarShortcut(new KeyboardEvent('keydown', key({ ctrlKey: true })), true)).toBe(
      false
    )
    expect(isSidebarShortcut(new KeyboardEvent('keydown', key({ ctrlKey: true })), false)).toBe(
      true
    )
  })

  it('never fires with Shift or Alt', () => {
    const shifted = new KeyboardEvent('keydown', key({ metaKey: true, shiftKey: true }))
    const alted = new KeyboardEvent('keydown', key({ metaKey: true, altKey: true }))
    expect(isSidebarShortcut(shifted, true)).toBe(false)
    expect(isSidebarShortcut(alted, true)).toBe(false)
  })

  it('hints per platform', () => {
    expect(sidebarShortcutHint(true)).toBe('⌘J')
    expect(sidebarShortcutHint(false)).toBe('Ctrl J')
  })
})

describe('useSidebarHotkey', () => {
  it('calls back on the chord and prevents the default', () => {
    const onToggle = vi.fn()
    const { unmount } = renderHook(() => useSidebarHotkey(onToggle))
    const mac = navigator.platform.toLowerCase().includes('mac')
    const event = new KeyboardEvent(
      'keydown',
      key(mac ? { metaKey: true, cancelable: true } : { ctrlKey: true, cancelable: true })
    )
    window.dispatchEvent(event)
    expect(onToggle).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
    unmount()
    window.dispatchEvent(new KeyboardEvent('keydown', key({ metaKey: true, ctrlKey: true })))
    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it('stays quiet when disabled', () => {
    const onToggle = vi.fn()
    renderHook(() => useSidebarHotkey(onToggle, false))
    window.dispatchEvent(new KeyboardEvent('keydown', key({ metaKey: true })))
    window.dispatchEvent(new KeyboardEvent('keydown', key({ ctrlKey: true })))
    expect(onToggle).not.toHaveBeenCalled()
  })
})
