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

export function isPaletteShortcut(event: KeyLike, mac: boolean): boolean {
  if (event.key.toLowerCase() !== 'k' || event.isComposing === true) return false
  if (event.altKey || event.shiftKey) return false
  return mac ? event.metaKey && !event.ctrlKey : event.ctrlKey && !event.metaKey
}

export function paletteShortcutHint(mac: boolean): string {
  return mac ? '⌘K' : 'Ctrl K'
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
