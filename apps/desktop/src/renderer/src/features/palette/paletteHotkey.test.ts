import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { isPaletteShortcut, paletteShortcutHint, usePaletteHotkey } from './paletteHotkey'

const key = (
  over: Partial<KeyboardEventInit> = {}
): { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean } => ({
  key: 'k',
  metaKey: false,
  ctrlKey: false,
  altKey: false,
  shiftKey: false,
  ...over
})

describe('isPaletteShortcut', () => {
  it('is ⌘K on macOS and Ctrl+K elsewhere', () => {
    expect(isPaletteShortcut(key({ metaKey: true }), true)).toBe(true)
    expect(isPaletteShortcut(key({ ctrlKey: true }), true)).toBe(false)
    expect(isPaletteShortcut(key({ ctrlKey: true }), false)).toBe(true)
    expect(isPaletteShortcut(key({ metaKey: true }), false)).toBe(false)
  })

  it('accepts an uppercase K (caps lock) but refuses extra modifiers', () => {
    expect(isPaletteShortcut(key({ key: 'K', metaKey: true }), true)).toBe(true)
    expect(isPaletteShortcut(key({ metaKey: true, shiftKey: true }), true)).toBe(false)
    expect(isPaletteShortcut(key({ metaKey: true, altKey: true }), true)).toBe(false)
  })

  it('ignores other keys and IME composition', () => {
    expect(isPaletteShortcut(key({ key: 'j', metaKey: true }), true)).toBe(false)
    expect(isPaletteShortcut({ ...key({ metaKey: true }), isComposing: true }, true)).toBe(false)
  })
})

describe('paletteShortcutHint', () => {
  it('names the platform shortcut', () => {
    expect(paletteShortcutHint(true)).toBe('⌘K')
    expect(paletteShortcutHint(false)).toBe('Ctrl K')
  })
})

describe('usePaletteHotkey', () => {
  afterEach(() => vi.restoreAllMocks())

  it('toggles on the shortcut and swallows the browser default', () => {
    const onToggle = vi.fn()
    const mac = /mac/i.test(navigator.platform)
    const { unmount } = renderHook(() => usePaletteHotkey(onToggle))
    const event = new KeyboardEvent('keydown', {
      key: 'k',
      metaKey: mac,
      ctrlKey: !mac,
      cancelable: true
    })
    window.dispatchEvent(event)
    expect(onToggle).toHaveBeenCalledOnce()
    expect(event.defaultPrevented).toBe(true)
    unmount()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: mac, ctrlKey: !mac }))
    expect(onToggle).toHaveBeenCalledOnce()
  })

  it('leaves other keys alone', () => {
    const onToggle = vi.fn()
    renderHook(() => usePaletteHotkey(onToggle))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k' }))
    expect(onToggle).not.toHaveBeenCalled()
  })
})
