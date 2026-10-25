// SOLUSDEV-317 — ⌘K (macOS) / Ctrl+K (elsewhere) toggles the command palette
// from anywhere in the workspace shell. A renderer keydown listener, not a
// global OS hotkey: it only fires while a Solus window has focus.
import { useEffect } from 'react'
import { isMac } from '../sol/commandHotkey'

interface KeyLike {
  readonly key: string
  readonly metaKey: boolean
  readonly ctrlKey: boolean
  readonly altKey: boolean
  readonly shiftKey: boolean
  readonly isComposing?: boolean
}

/** ⌘<key> on macOS, Ctrl+<key> elsewhere; never with Shift or Alt, never mid-composition. */
export function isModKeyShortcut(event: KeyLike, mac: boolean, key: string): boolean {
  if (event.key.toLowerCase() !== key.toLowerCase() || event.isComposing === true) return false
  if (event.altKey || event.shiftKey) return false
  return mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey
}

export function isPaletteShortcut(event: KeyLike, mac: boolean): boolean {
  return isModKeyShortcut(event, mac, 'k')
}

/** `⌘K` / `Ctrl K` style hint for a modifier shortcut. */
export function modKeyHint(mac: boolean, key: string): string {
  return mac ? `⌘${key.toUpperCase()}` : `Ctrl ${key.toUpperCase()}`
}

export function paletteShortcutHint(mac: boolean): string {
  return modKeyHint(mac, 'k')
}

/** `onToggle` should be stable (a module-level function); a new one re-binds the listener. */
export function usePaletteHotkey(onToggle: () => void): void {
  useEffect(() => {
    const mac = isMac()
    const onKey = (event: KeyboardEvent): void => {
      if (!isPaletteShortcut(event, mac)) return
      event.preventDefault()
      onToggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onToggle])
}
